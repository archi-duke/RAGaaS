"""
LLM (Chat Completions) 프록시 라우터
- 수신 요청에 지정된 필수 헤더 검증
- 검증 통과 시 Samsung DS LLM API로 중계 (streaming 포함)
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import logging

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# 수신 요청에서 검증할 필수 헤더 이름 (case-insensitive)
REQUIRED_HEADERS = [
    "x-dep-ticket",       # 인증 티켓
    "send-system-name",   # 시스템 명칭
    "user-id",            # 호출자 AD ID
    "user-type",          # 호출자 유형 (AD_ID 등)
]


@router.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    """
    OpenAI 호환 Chat Completions 엔드포인트.
    필수 헤더를 검증한 뒤 Samsung DS LLM API로 중계합니다.
    stream=true 시 SSE 스트리밍도 그대로 중계합니다.

    필수 헤더:
      - x-dep-ticket      : Samsung DS 인증 티켓
      - send-system-name  : 시스템 명칭 (예: ai4se)
      - user-id           : 호출자 AD ID (예: jinwone.choi)
      - user-type         : 호출자 유형 (예: AD_ID)
    """
    # ── Guard: 필수 헤더 존재 여부 확인 ─────────────────────────────
    missing = [h for h in REQUIRED_HEADERS if not request.headers.get(h)]
    if missing:
        logger.warning(f"[LLM] 필수 헤더 누락: {missing} — 요청 거부")
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Missing required headers",
                "missing": missing,
                "required": REQUIRED_HEADERS,
            }
        )

    body = await request.json()
    is_stream = body.get("stream", False)
    logger.info(
        f"[LLM] 공식 OpenAI로 중계 시작: model={body.get('model')}, stream={is_stream}"
    )

    # ── 업스트림 헤더 구성 (공식 OpenAI 호출용) ──────────────────
    upstream_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
    }

    try:
        if is_stream:
            # ── 스트리밍 응답 중계 ──────────────────────────────────
            async def stream_generator():
                async with httpx.AsyncClient(
                    verify=settings.SSL_VERIFY,
                    timeout=settings.REQUEST_TIMEOUT
                ) as client:
                    async with client.stream(
                        "POST",
                        settings.LLM_TARGET_URL,
                        json=body,
                        headers=upstream_headers,
                    ) as resp:
                        logger.info(f"[LLM] 스트리밍 업스트림 status={resp.status_code}")
                        async for chunk in resp.aiter_bytes():
                            yield chunk

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        else:
            # ── 일반 응답 중계 ──────────────────────────────────────
            async with httpx.AsyncClient(
                verify=settings.SSL_VERIFY,
                timeout=settings.REQUEST_TIMEOUT
            ) as client:
                resp = await client.post(
                    settings.LLM_TARGET_URL,
                    json=body,
                    headers=upstream_headers,
                )
            logger.info(f"[LLM] 업스트림 응답: status={resp.status_code}")
            return JSONResponse(content=resp.json(), status_code=resp.status_code)

    except httpx.TimeoutException:
        logger.error("[LLM] 업스트림 타임아웃")
        raise HTTPException(status_code=504, detail="Upstream LLM API timeout")
    except Exception as e:
        logger.error(f"[LLM] 오류: {e}")
        raise HTTPException(status_code=502, detail=f"Upstream LLM API error: {str(e)}")
