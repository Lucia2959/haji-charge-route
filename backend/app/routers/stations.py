from fastapi import APIRouter, HTTPException

from ..models import StationDetail
from ..services import ev_stations

router = APIRouter(prefix="/api/stations", tags=["stations"])


@router.get("/{station_id}", response_model=StationDetail)
async def station_detail(station_id: str) -> StationDetail:
    """충전소 상세 + 실시간 충전현황."""
    detail = await ev_stations.get_station_detail(station_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="충전소를 찾을 수 없습니다.")
    return detail
