"""
임베딩 프록시 라우터
- 수신 요청에 x-dep-ticket 헤더 필수
- 검증 통과 시 Samsung DS 임베딩 API로 중계
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import logging

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# 수신 요청에서 검증할 필수 헤더 이름 (case-insensitive)
REQUIRED_HEADERS = ["x-dep-ticket"]


@router.post("/v1/embeddings/embeddings")
@router.post("/v1/embeddings")
async def proxy_embeddings(request: Request):
    """
    OpenAI 호환 임베딩 엔드포인트.
    필수 헤더를 검증한 뒤 Samsung DS 임베딩 API로 중계합니다.

    필수 헤더:
      - x-dep-ticket: Samsung DS 인증 티켓
    """
    # ── Guard: 필수 헤더 존재 여부 확인 ─────────────────────────────
    missing = [h for h in REQUIRED_HEADERS if not request.headers.get(h)]
    if missing:
        logger.warning(f"[Embedding] 필수 헤더 누락: {missing} — 요청 거부")
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Missing required headers",
                "missing": missing,
                "required": REQUIRED_HEADERS,
            }
        )

    body = await request.json()
    logger.info(f"[Embedding] 공식 OpenAI로 중계 시작 (input 길이={len(str(body.get('input', '')))})")

    # ── 업스트림 헤더 구성 (공식 OpenAI 호출용) ──────────────────
    upstream_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
    }

    try:
        async with httpx.AsyncClient(verify=settings.SSL_VERIFY, timeout=settings.REQUEST_TIMEOUT) as client:
            resp = await client.post(
                settings.EMBEDDING_TARGET_URL,
                json=body,
                headers=upstream_headers,
            )
        logger.info(f"[Embedding] 업스트림 응답: status={resp.status_code}")
        return JSONResponse(content=resp.json(), status_code=resp.status_code)

    except httpx.TimeoutException:
        logger.error("[Embedding] 업스트림 타임아웃")
        raise HTTPException(status_code=504, detail="Upstream embedding API timeout")
    except Exception as e:
        logger.error(f"[Embedding] 오류: {e}")
        raise HTTPException(status_code=502, detail=f"Upstream embedding API error: {str(e)}")
