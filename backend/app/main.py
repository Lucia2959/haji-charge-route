from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, http
from .config import settings
from .http import QuotaExceeded, RateLimited
from .ratelimit import rate_limit_middleware
from .routers import internal, places, route, stations, weather


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 생존 동안 외부기관용 공유 커넥션 풀 유지, 종료 시 정리.
    # db.connect()는 실패해도 예외를 내지 않는다 — DB는 혼잡 예측 전용이고,
    # 그것 때문에 경로 계획까지 못 뜨면 안 된다.
    await db.connect()
    yield
    await db.aclose()
    await http.aclose()


# 운영(APP_ENV=production)에서는 API 문서를 노출하지 않는다.
app = FastAPI(
    title="Haji Charge Route API",
    version="0.1.0",
    docs_url=None if settings.is_prod else "/docs",
    redoc_url=None if settings.is_prod else "/redoc",
    openapi_url=None if settings.is_prod else "/openapi.json",
    lifespan=lifespan,
)


# 외부 API 무료 사용량 초과/과금 발생 → 화면에 "사용량이 초과하였습니다"로 구분 표시.
# (network 오류·내부 호출제한 429와 구분: 여기는 402 Payment Required)
@app.exception_handler(QuotaExceeded)
async def _quota_exceeded_handler(request: Request, exc: QuotaExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=402,
        content={"detail": "사용량이 초과하였습니다", "code": "quota_exceeded"},
    )


# 단시간 과다호출(HTTP 429)은 쿼터 '소진'과 다르다 — 잠시 뒤면 풀린다.
# 이걸 '사용량 초과'로 표시하면 사용자가 오늘은 못 쓴다고 오해한다.
@app.exception_handler(RateLimited)
async def _rate_limited_handler(request: Request, exc: RateLimited) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": "외부 지도·충전소 서비스 요청이 몰리고 있습니다. 잠시 후 다시 시도해 주세요.",
            "code": "upstream_rate_limited",
        },
        headers={"Retry-After": "60"},
    )

# 요청 제한(IP·경로별) — 개인/내부용 인메모리 제한
app.middleware("http")(rate_limit_middleware)


# 공유 시크릿 검사 — api_token이 설정된 경우에만 동작(로컬 개발은 비워두면 통과).
# rate limit보다 바깥(나중에 등록 = 먼저 실행)에 두어, 토큰 없는 요청은 제한 카운트를
# 소모하지 않고 즉시 차단한다.
@app.middleware("http")
async def require_token(request: Request, call_next):
    if settings.api_token and request.url.path.startswith("/api/"):
        # CORS preflight는 커스텀 헤더를 실어 보내지 않으므로 통과시킨다.
        if request.method != "OPTIONS" and request.headers.get("X-Haji-Key") != settings.api_token:
            return JSONResponse(status_code=401, content={"detail": "접근 권한이 없습니다"})
    return await call_next(request)


# 기본 보안 헤더 (개인 테스트에도 무해, 외부 공개 시 필수)
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Haji-Key"],
)

app.include_router(route.router)
app.include_router(stations.router)
app.include_router(places.router)
app.include_router(weather.router)
app.include_router(internal.router)


@app.get("/health")
def health() -> dict:
    # 운영에서는 상태만 노출한다. 키 설정 여부·mock 여부는 공격자에게 유용한 정보라
    # 개발 환경에서만 함께 반환한다.
    if settings.is_prod:
        return {"status": "ok"}
    return {
        "status": "ok",
        "kakao": settings.use_kakao,
        "ev_api": settings.use_ev_api,
        "mock_enabled": settings.mock_enabled,
        "app_env": settings.app_env,
    }
