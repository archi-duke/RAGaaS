"""LLM(챗) 호출 단일 진입점.

RAGaaS 의 모든 LLM 챗 호출은 이 모듈의 achat()/chat() 한 경로로 통일한다.
- 프록시 없이 프로바이더(사외 OpenAI/Anthropic 또는 사내 게이트웨이)를 raw HTTP 로 직접 호출.
- 인증·부가정보는 resolved config 의 extra_headers(X-Dep-Ticket, Send-System-Name,
  User-Id, User-Type, Chat-Id 등)로 전달. api_key 가 있으면 Bearer 도 추가.
- 사내 gpt-oss 계열은 답이 message.content 대신 reasoning_content/reasoning 로 오므로
  그 필드에서 답을 읽는다(응답 파싱이지 임의 fallback 이 아님).

원칙: 실패는 숨기지 않는다.
  네트워크 오류 / 4xx·5xx / 빈 응답 / 모델·자격정보 미설정은 모두 LLMError 로 올려
  호출자·사용자에게 그대로 전달한다. 임의 모델 기본값이나 조용한 빈 결과 반환은 하지 않는다.
  (임의 fallback 은 착오로 인한 잘못된 결과를 유발할 수 있음)
"""
import asyncio
import os
import random
import threading
import time
from typing import Any, AsyncIterator, Optional, List, Dict
from urllib.parse import urlparse

import httpx

DEFAULT_TIMEOUT = 120.0

# ── 공급자별 동시 호출 제한 + 429 재시도 ───────────────────────────────────────
# Z.ai(GLM)는 같은 키로 동시 8개를 보내면 429 "Rate limit reached for requests" 를 준다 (2026-11-16 측정, 4개는 정상).
# 에이전틱 필터의 동시 하위 검색이나 여러 사용자의 동시 검색이 한도를 넘지 않도록 호스트별로 줄을 세운다.
# 429 는 잠깐 기다렸다 다시 시도하고, 그래도 실패하면 LLMError 로 올린다 (실패를 숨기지 않음).
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "4"))
LLM_RATE_RETRIES = int(os.getenv("LLM_RATE_RETRIES", "3"))
_async_sems: Dict[tuple, asyncio.Semaphore] = {}
_sync_sems: Dict[str, threading.BoundedSemaphore] = {}
_sync_lock = threading.Lock()


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def _async_sem(url: str) -> asyncio.Semaphore:
    key = (_host(url), id(asyncio.get_running_loop()))
    sem = _async_sems.get(key)
    if sem is None:
        sem = _async_sems[key] = asyncio.Semaphore(LLM_MAX_CONCURRENCY)
    return sem


def _sync_sem(url: str) -> threading.BoundedSemaphore:
    h = _host(url)
    with _sync_lock:
        if h not in _sync_sems:
            _sync_sems[h] = threading.BoundedSemaphore(max(1, LLM_MAX_CONCURRENCY // 2))
        return _sync_sems[h]


def _retry_wait(resp: "httpx.Response", attempt: int) -> float:
    ra = resp.headers.get("retry-after")
    try:
        if ra:
            return min(10.0, float(ra))
    except ValueError:
        pass
    return min(8.0, (2 ** attempt) * 0.8) + random.uniform(0, 0.4)


class LLMError(RuntimeError):
    """LLM 호출 실패. 사용자에게 전달되어 조치를 유도한다 (임의 fallback 금지)."""


# ── 헤더 / 엔드포인트 구성 ────────────────────────────────────────────────────

def chat_endpoint(base_url: Optional[str]) -> str:
    """base_url 로부터 chat/completions 전체 URL 을 만든다.

    resolved base_url 은 보통 `http(s)://host[/v1]` 형태이므로 `/chat/completions` 를
    붙인다. 이미 전체 경로면 그대로 둔다.
    """
    if not base_url:
        return "https://api.openai.com/v1/chat/completions"
    b = base_url.rstrip("/")
    return b if b.endswith("/chat/completions") else b + "/chat/completions"


def build_headers(api_key: Optional[str], extra_headers: Optional[dict] = None) -> dict:
    """사내/사외 게이트웨이 호출 헤더를 만든다.

    extra_headers(X-Dep-Ticket 등)를 우선 싣고, 별도 Authorization 이 없고 api_key 가
    있으면 Bearer 를 추가한다. 사내 게이트웨이는 헤더 인증만 쓰고 api_key 가 없을 수 있다.
    """
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if api_key and not any(k.lower() == "authorization" for k in headers):
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def has_credentials(cfg: Optional[dict]) -> bool:
    """호출에 필요한 자격정보(키 또는 인증 헤더)가 있는지."""
    cfg = cfg or {}
    return bool(cfg.get("api_key") or cfg.get("extra_headers"))


# ── 응답 파싱 ────────────────────────────────────────────────────────────────

def extract_content_from_dict(data: Any) -> str:
    """raw HTTP(JSON dict) 응답에서 답 텍스트를 추출한다.

    content 우선 → reasoning_content → reasoning (사내 gpt-oss).
    아무 답도 없으면 빈 문자열을 반환한다(호출부에서 실패로 처리).
    """
    try:
        message = (data.get("choices") or [])[0].get("message") or {}
    except (AttributeError, IndexError, TypeError):
        return ""
    content = message.get("content")
    if content and content.strip():
        return content
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if value and str(value).strip():
            return str(value)
    return content or ""


def _truncate(s: str, n: int = 500) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "...(truncated)"


def _build_payload(
    cfg: dict,
    messages: List[Dict[str, str]],
    model: Optional[str],
    temperature: Optional[float],
    max_tokens: Optional[int],
    response_format: Optional[dict],
    extra_body: Optional[dict],
) -> dict:
    resolved_model = model or (cfg or {}).get("model")
    if not resolved_model:
        raise LLMError("LLM 모델이 지정되지 않았습니다. KB 또는 요청에서 LLM 모델을 먼저 선택하세요.")
    if not has_credentials(cfg):
        raise LLMError(
            "LLM 자격정보가 없습니다. 프로바이더에 API Key 또는 인증 헤더(extra_headers)를 설정하세요."
        )
    if not messages:
        raise LLMError("LLM 호출 messages 가 비어 있습니다.")
    payload: dict = {"model": resolved_model, "messages": messages}
    if is_reasoning_model(resolved_model):
        # OpenAI 추론 모델(gpt-5, o-시리즈): temperature 는 기본값(1)만 허용, max_tokens 대신
        # max_completion_tokens (추론 토큰 포함이므로 넉넉히). 추론 강도는 기본 low.
        if max_tokens is not None:
            payload["max_completion_tokens"] = max(max_tokens * 4, 4000)
        payload["reasoning_effort"] = "low"
    else:
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
    if response_format is not None:
        payload["response_format"] = response_format
    if extra_body:
        payload.update(extra_body)
    return payload


def _handle_response(status_code: int, text: str, url: str, model: str) -> str:
    if status_code >= 400:
        raise LLMError(
            f"LLM 호출 오류 {status_code} (endpoint={url}, model={model}): {_truncate(text)}"
        )
    try:
        import json as _json
        data = _json.loads(text)
    except Exception as e:
        raise LLMError(f"LLM 응답 파싱 실패 (endpoint={url}): {_truncate(text)}") from e
    answer = extract_content_from_dict(data)
    if not answer or not answer.strip():
        raise LLMError(
            f"LLM 응답이 비어 있습니다 (endpoint={url}, model={model}). "
            f"모델/게이트웨이 설정을 확인하세요."
        )
    return answer


def is_reasoning_model(model: Optional[str]) -> bool:
    """OpenAI 추론 모델 여부 (gpt-5 계열 — chat 변형 제외, o1/o3/o4 계열)."""
    m = (model or "").lower()
    if m.startswith("gpt-5"):
        return "chat" not in m
    return m.startswith(("o1", "o3", "o4"))


def no_thinking_extra_body(model: Optional[str]) -> Optional[dict]:
    """추론 모델(z.ai GLM 계열)의 사고과정 출력 비활성 옵션. 그 외 모델은 None."""
    if model and "glm" in model.lower():
        return {"thinking": {"type": "disabled"}}
    return None


async def achat(
    cfg: dict,
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[dict] = None,
    extra_body: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """비동기 LLM 챗 호출(단일 진입점). 실패 시 LLMError 를 올린다."""
    payload = _build_payload(cfg, messages, model, temperature, max_tokens, response_format, extra_body)
    url = chat_endpoint((cfg or {}).get("base_url"))
    headers = build_headers((cfg or {}).get("api_key"), (cfg or {}).get("extra_headers"))
    sem = _async_sem(url)
    for attempt in range(LLM_RATE_RETRIES + 1):
        try:
            async with sem:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
        except httpx.RequestError as e:
            raise LLMError(f"LLM 게이트웨이 연결 실패 (endpoint={url}): {e}") from e
        if resp.status_code == 429 and attempt < LLM_RATE_RETRIES:
            await asyncio.sleep(_retry_wait(resp, attempt))   # 줄 밖에서 기다린다
            continue
        return _handle_response(resp.status_code, resp.text, url, payload["model"])


async def achat_stream(
    cfg: dict,
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    extra_body: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> AsyncIterator[str]:
    """스트리밍 챗 (OpenAI 호환 SSE). 생성되는 대로 텍스트 조각을 내보낸다 — 답변 첫 글자를 일찍 보여 주기 위함.

    429 는 스트림이 시작되기 전에만 재시도한다. 오류·빈 응답은 LLMError (실패를 숨기지 않음).
    """
    import json as _json
    payload = _build_payload(cfg, messages, model, temperature, max_tokens, None, extra_body)
    payload["stream"] = True
    url = chat_endpoint((cfg or {}).get("base_url"))
    headers = build_headers((cfg or {}).get("api_key"), (cfg or {}).get("extra_headers"))
    sem = _async_sem(url)
    got_any = False
    for attempt in range(LLM_RATE_RETRIES + 1):
        retry = False
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        if resp.status_code == 429 and attempt < LLM_RATE_RETRIES:
                            retry = True
                            wait = _retry_wait(resp, attempt)
                        elif resp.status_code >= 400:
                            body = (await resp.aread()).decode("utf-8", "replace")
                            _handle_response(resp.status_code, body, url, payload["model"])
                        else:
                            async for line in resp.aiter_lines():
                                line = line.strip()
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    break
                                try:
                                    ev = _json.loads(data)
                                except ValueError:
                                    continue
                                for ch in ev.get("choices") or []:
                                    d = ch.get("delta") or {}
                                    piece = d.get("content") or ""
                                    if piece:
                                        got_any = True
                                        yield piece
            except httpx.RequestError as e:
                raise LLMError(f"LLM 게이트웨이 연결 실패 (endpoint={url}): {e}") from e
        if retry:
            await asyncio.sleep(wait)
            continue
        break
    if not got_any:
        raise LLMError(f"LLM 스트림 응답이 비었습니다 (endpoint={url}, model={payload['model']})")


def chat(
    cfg: dict,
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[dict] = None,
    extra_body: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """동기 LLM 챗 호출(단일 진입점). 실패 시 LLMError 를 올린다."""
    payload = _build_payload(cfg, messages, model, temperature, max_tokens, response_format, extra_body)
    url = chat_endpoint((cfg or {}).get("base_url"))
    headers = build_headers((cfg or {}).get("api_key"), (cfg or {}).get("extra_headers"))
    sem = _sync_sem(url)
    for attempt in range(LLM_RATE_RETRIES + 1):
        try:
            with sem:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.post(url, headers=headers, json=payload)
        except httpx.RequestError as e:
            raise LLMError(f"LLM 게이트웨이 연결 실패 (endpoint={url}): {e}") from e
        if resp.status_code == 429 and attempt < LLM_RATE_RETRIES:
            time.sleep(_retry_wait(resp, attempt))
            continue
        return _handle_response(resp.status_code, resp.text, url, payload["model"])
