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
from typing import Any, Optional, List, Dict
from urllib.parse import urlparse

import httpx

# 공급자별 동시 호출 제한 + 429 재시도 (backend core/llm 과 같은 정책, PR #60).
# Z.ai(GLM)는 같은 키로 동시 8개면 429 — 재추출은 문서 2 × 청크 4 = 8 동시라 적재 모델을 GLM 으로 바꾸면 걸린다.
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

DEFAULT_TIMEOUT = 120.0


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
    m = resolved_model.lower()
    if (m.startswith("gpt-5") and "chat" not in m) or m.startswith(("o1", "o3", "o4")):
        # OpenAI 추론 모델: temperature 기본값만 허용, max_completion_tokens 사용 (backend llm.py 와 동일)
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
            await asyncio.sleep(_retry_wait(resp, attempt))
            continue
        return _handle_response(resp.status_code, resp.text, url, payload["model"])


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
