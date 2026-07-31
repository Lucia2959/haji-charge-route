"""충전소 상세 라우터 (화면 S-04).

프런트가 10초마다 폴링하지만, 서비스 계층에 20초 상태 캐시가 있어 실제 외부 API
호출은 20초에 1회다(`ev_stations._STATUS_TTL`).
"""

from fastapi import APIRouter, HTTPException

from ..models import StationDetail
from ..services import ev_stations

router = APIRouter(prefix="/api/stations", tags=["stations"])


@router.get("/{station_id}", response_model=StationDetail)
async def station_detail(station_id: str) -> StationDetail:
    """충전소 상세 + 실시간 충전현황.

    station_id로 시군구를 역인덱스(`_station_region`)에서 찾아 조회 범위를 좁힌다.
    이 인덱스는 **카탈로그 조회 시에만 채워지므로**, 서버 재시작 후 경로계획을 한 번도
    돌리지 않은 상태에서 상세를 직접 열면 404가 난다(정상 흐름: 계획 → 상세).
    """
    detail = await ev_stations.get_station_detail(station_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="충전소를 찾을 수 없습니다.")
    return detail
