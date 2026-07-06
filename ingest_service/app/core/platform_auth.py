"""플랫폼 신원 확정 미들웨어 — 플랫폼 계약 docs/platform-contract/05 §1~§3 의 파이썬 어댑터.

요청마다 행위 사용자(user_id)를 확정해 request.state.user_id 에 싣는다.
핸들러는 이 값만 신뢰한다 — body/쿼리의 user 필드 신뢰 금지.

알고리즘 (계약 05 §1):
  1. OPTIONS                          → 통과 (preflight)
  2. 공개 경로                         → 통과 (신원 없음)
  3. X-Service-Token 헤더 존재:
       constant-time 비교로 env SERVICE_TOKEN 과 일치?
         일치   → user_id = X-User-Id 헤더 (act-as). introspect 생략. 통과
         불일치 → 401  (SERVICE_TOKEN 미설정이면 항상 거부 — 열리는 폴백 금지)
  4. env USE_SSO == "true":
       Authorization: Bearer <token> → introspect (사내 SSO 로 나가는 outbound 검증)
         성공 → user_id = loginid / 실패 → 401
  5. (dev 폴백): X-User-Id → X-Dev-User → env DEV_USER

주의: Starlette HTTP 미들웨어는 WebSocket 을 가로채지 않는다 — /api/v2/ws 는 이 미들웨어의
보호 범위 밖이다 (셸/게이트웨이 경유 전제. WS 자체 인증은 후속 과제).
"""
import hmac
import os

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

# 신원 없이 통과하는 공개 경로 (서비스별 자체 정의 — 계약 05 §1-2)
PUBLIC_PATHS = (
    "/",             # 루트 안내 (exact)
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
)

_introspect_client: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _introspect_client
    if _introspect_client is None:
        verify = os.getenv("SSO_INSECURE_TLS", "false").lower() != "true"
        _introspect_client = httpx.AsyncClient(verify=verify, timeout=3.0)
    return _introspect_client


def _is_public(path: str) -> bool:
    if path == "/":
        return True
    return any(p != "/" and (path == p or path.startswith(p + "/")) for p in PUBLIC_PATHS) \
        or path.endswith("/health")


async def introspect(token: str) -> str | None:
    """사내 SSO 로 나가는 토큰 검증 (계약 05 §2). 성공 시 loginid, 실패 시 None."""
    base = os.environ.get("SSO_INTROSPECT_URL", "").rstrip("/")
    if not base:
        return None
    try:
        r = await _client().get(f"{base}/Account/introspect", params={"token": token})
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        d = r.json()
    except ValueError:
        return None
    if not d.get("loginid") or d.get("active") == "false":
        return None
    return d["loginid"]


async def platform_auth_middleware(request: Request, call_next):
    # 1. preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    # 2. 공개 경로
    if _is_public(request.url.path):
        return await call_next(request)

    headers = request.headers

    # 3. 서비스간 인증 (X-Service-Token)
    service_token = headers.get("X-Service-Token")
    if service_token is not None:
        expected = os.getenv("SERVICE_TOKEN", "")
        if expected and hmac.compare_digest(service_token, expected):
            request.state.user_id = headers.get("X-User-Id", "")
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "invalid service token"})

    # 4. SSO 모드 — Bearer + introspect
    if os.getenv("USE_SSO", "false").lower() == "true":
        auth = headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        loginid = await introspect(token) if token else None
        if not loginid:
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        request.state.user_id = loginid
        return await call_next(request)

    # 5. dev 폴백
    request.state.user_id = (
        headers.get("X-User-Id")
        or headers.get("X-Dev-User")
        or os.getenv("DEV_USER", "dev")
    )
    return await call_next(request)


def get_user_id(request: Request) -> str:
    """핸들러에서 확정 신원 조회용 헬퍼."""
    return getattr(request.state, "user_id", "")


def service_headers(user_id: str = "") -> dict:
    """서비스간 호출 헤더 (플랫폼 계약 05 §3) — X-Service-Token + act-as X-User-Id."""
    headers: dict = {}
    token = os.getenv("SERVICE_TOKEN", "")
    if token:
        headers["X-Service-Token"] = token
    if user_id:
        headers["X-User-Id"] = user_id
    return headers
