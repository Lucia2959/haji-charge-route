"""내부 운영용 엔드포인트 — 외부 크론(cron-job.org)이 호출한다.

사용자 경로(/api/*)와 분리한 이유는 세 가지다.

  1. **토큰이 다르다.** /api/*의 API_TOKEN은 프런트 번들에 그대로 노출되므로,
     그 토큰으로 수집을 트리거할 수 있으면 URL만 아는 누구나 공공 API 쿼터를
     태울 수 있다. COLLECT_TOKEN은 서버에만 둔다.
  2. **요청 제한이 다르다.** 5분에 1회 오는 크론이라 분당 2회면 충분하다.
  3. **/collect가 keep-alive를 겸한다.** Render 무료는 15분 유휴 시 슬립하는데,
     이 호출이 5분마다 오므로 별도 keep-alive 크론이 필요 없다.
     (기존 /health 크론을 이것으로 대체한다 — DEPLOY.md 참고)

수집기 자체는 사용자 요청 처리 경로에 들어가지 않는다. 다만 같은 프로세스·같은
이벤트 루프를 쓴다(Render 무료에 Background Worker가 없다). 영향은 XML 파싱
CPU 약 0.26초가 5분에 한 번 들어가는 정도다.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Header, HTTPException

from ..config import settings
from ..services import collector, congestion


async def _require_collect_token(
    x_collect_key: str | None = Header(default=None),
) -> None:
    """COLLECT_TOKEN이 설정돼 있으면 일치해야 통과.

    비어 있으면(로컬 개발) 검사하지 않는다. 운영에서는 반드시 설정할 것 —
    Render 대시보드 환경변수. render.yaml에 sync:false로 선언돼 있다.
    """
    if settings.collect_token and x_collect_key != settings.collect_token:
        raise HTTPException(status_code=401, detail="접근 권한이 없습니다")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(_require_collect_token)],
    include_in_schema=False,
)

# 크론이 겹쳐 발화하거나 이전 실행이 느릴 때 같은 수집이 두 번 돌지 않게 한다.
# 겹치면 공공 API 호출이 두 배가 되고 예산만 축난다.
_collect_lock = asyncio.Lock()
_aggregate_lock = asyncio.Lock()


@router.post("/collect")
async def collect() -> dict:
    """상태 피드 1회 수집 → 완료 세션 적재. 5분마다 호출한다.

    피드 윈도가 10분 고정이라 **10분을 넘겨 호출하면 그 사이 변경을 영구히 놓친다.**
    크론 주기를 늘리지 말 것.
    """
    if _collect_lock.locked():
        # 이전 수집이 아직 도는 중 — 건너뛴다. 다음 발화(5분 뒤)가 윈도 안이라 손실 없다.
        return {"ok": False, "reason": "already_running"}
    async with _collect_lock:
        return await collector.collect_once()


@router.post("/aggregate")
async def aggregate() -> dict:
    """세션 → occupancy_stat 재집계 + 보관기간 초과분 삭제. 하루 1회 호출한다.

    수십 초 걸릴 수 있으나 사용자 응답 경로가 아니다. 새벽(KST 04시경)을 권장한다.
    """
    if _aggregate_lock.locked():
        return {"ok": False, "reason": "already_running"}
    async with _aggregate_lock:
        return await congestion.aggregate()
