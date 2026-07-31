"""출발지 현재 기온 조회 — Open-Meteo (API 키·신고 불필요, 무료).

기상청 data.go.kr 단기예보는 '위치기반서비스사업 신고'가 있어야 승인되므로,
키·신고가 전혀 필요 없는 Open-Meteo로 대체한다. 위경도로 현재기온을 바로 받는다.
실패 시 None → 프론트는 수동 기온을 유지한다.

주의: Open-Meteo는 비상업 무료(일 1만 콜). 상업 배포 시 상업 플랜 또는
      OpenWeatherMap 등으로 교체 (current_temperature 만 바꾸면 됨).
"""

from __future__ import annotations

import httpx

from ..http import client as _http
from ..models import LatLng

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


async def current_temperature(loc: LatLng) -> float | None:
    """출발지 현재 기온(°C). 실패 시 None (기온은 비치명 → 사용량초과도 조용히 None)."""
    try:
        r = await _http().get(
            OPEN_METEO_URL,
            params={
                "latitude": loc.lat,
                "longitude": loc.lng,
                "current": "temperature_2m",
                "timezone": "Asia/Seoul",
            },
            timeout=10,
        )
        r.raise_for_status()
        temp = r.json().get("current", {}).get("temperature_2m")
        return float(temp) if temp is not None else None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
