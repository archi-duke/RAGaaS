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
from typing import Any, Optional, List, Dict

import httpx

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
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as e:
        raise LLMError(f"LLM 게이트웨이 연결 실패 (endpoint={url}): {e}") from e
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
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
    except httpx.RequestError as e:
        raise LLMError(f"LLM 게이트웨이 연결 실패 (endpoint={url}): {e}") from e
    return _handle_response(resp.status_code, resp.text, url, payload["model"])
