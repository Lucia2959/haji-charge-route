"""아주 단순한 인메모리 IP·경로별 요청 제한 (개인 테스트/내부 공유용).

프로세스 메모리 기반이라 다중 워커에는 정확하지 않지만, 개발 단계에서
버튼 연타·자동 호출로 외부 API 쿼터가 소진되는 것을 막는 목적이다.
외부 공개·상용에서는 Redis 등 공유 저장소 기반 제한으로 교체해야 한다.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

# 경로 prefix → 분당 허용 횟수. 매칭 없으면 _DEFAULT_LIMIT 적용.
# 매칭은 startswith라 **prefix가 정확히 겹치지 않으면 기본값으로 샌다.**
# /api/route/warmup 이 그 사례였다 — plan 과 비용이 거의 같은데(지오코딩·경로조회·
# 카탈로그 수집을 그대로 수행) /api/route/plan 에 안 걸려 120/분을 받고 있었다.
# 사용자가 누르는 plan 과 달리 앱 진입 시 자동 발사되므로 더 낮게 잡는다.
_LIMITS: list[tuple[str, int]] = [
    ("/api/route/plan", 20),
    ("/api/route/warmup", 10),
    ("/api/places/search", 40),
    ("/api/weather/current", 40),
    ("/api/stations", 60),
]
_DEFAULT_LIMIT = 120
_WINDOW_SEC = 60.0

# (ip, bucket) → 최근 요청 타임스탬프 큐
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


# 주기적 정리: 다시 방문하지 않는 (ip, prefix) 키가 계속 쌓이면 메모리가 단조 증가한다.
# (IP를 바꿔가며 요청하면 무제한으로 늘어남) → 윈도우가 지난 키를 일정 간격으로 걷어낸다.
_SWEEP_EVERY_SEC = 300.0
_last_sweep = 0.0


def _sweep(now: float) -> None:
    global _last_sweep
    if now - _last_sweep < _SWEEP_EVERY_SEC:
        return
    _last_sweep = now
    stale = [k for k, q in _hits.items() if not q or now - q[-1] > _WINDOW_SEC]
    for k in stale:
        del _hits[k]


def _bucket(path: str) -> tuple[str, int]:
    for prefix, limit in _LIMITS:
        if path.startswith(prefix):
            return prefix, limit
    return "*", _DEFAULT_LIMIT


async def rate_limit_middleware(request: Request, call_next):
    # 헬스체크·문서는 제한하지 않음
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    ip = request.client.host if request.client else "unknown"
    prefix, limit = _bucket(path)
    key = (ip, prefix)
    now = time.monotonic()

    _sweep(now)

    q = _hits[key]
    while q and now - q[0] > _WINDOW_SEC:
        q.popleft()
    if len(q) >= limit:
        retry = max(1, int(_WINDOW_SEC - (now - q[0])))
        return JSONResponse(
            status_code=429,
            content={"detail": f"요청이 너무 많습니다. {retry}초 후 다시 시도해 주세요."},
            headers={"Retry-After": str(retry)},
        )
    q.append(now)
    return await call_next(request)
