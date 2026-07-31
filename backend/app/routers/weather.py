"""기온 조회 라우터 — 메인 화면의 기온 자동입력.

**부가기능이므로 절대 실패를 전파하지 않는다.** 위치를 못 찾든 Open-Meteo가 죽든
`temperature_c=None`을 돌려주고, 프런트는 사용자가 입력한 기온을 그대로 유지한다.
기온 하나 때문에 경로계획 화면 전체가 막히면 안 되기 때문이다.
"""

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
