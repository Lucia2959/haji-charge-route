from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..services import kakao, weather

router = APIRouter(prefix="/api/weather", tags=["weather"])


class WeatherResponse(BaseModel):
    temperature_c: float | None
    source: str  # "open-meteo" | "unavailable"


@router.get("/current", response_model=WeatherResponse)
async def current(query: str = Query(..., min_length=1, max_length=200, description="출발지 (주소·지명 또는 'lng,lat')")):
    """출발지 현재 기온 (Open-Meteo)."""
    try:
        loc = await kakao.geocode(query)
    except kakao.LocationNotFound:
        # 기온 조회는 부가기능이라 위치를 못 찾으면 조용히 미제공 처리
        return WeatherResponse(temperature_c=None, source="unavailable")
    temp = await weather.current_temperature(loc)
    return WeatherResponse(
        temperature_c=round(temp, 1) if temp is not None else None,
        source="open-meteo" if temp is not None else "unavailable",
    )
