"""충전소 상세 라우터 (화면 S-04).

프런트가 10초마다 폴링하지만, 서비스 계층에 20초 상태 캐시가 있어 실제 외부 API
호출은 20초에 1회다(`ev_stations._STATUS_TTL`).
"""

from fastapi import APIRouter, HTTPException, Query

from ..models import LatLng, StationDetail, StationSummary
from ..services import ev_stations, kakao

router = APIRouter(prefix="/api/stations", tags=["stations"])


# ⚠ /{station_id}보다 **먼저** 선언해야 한다. 아래에 두면 "district"가
#   station_id로 잡혀 404가 난다.
@router.get("/district", response_model=list[StationSummary])
async def district_stations(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    fast_only: bool = False,
    open_only: bool = True,
    min_kw: float = Query(0.0, ge=0, le=400),
    with_status: bool = False,
) -> list[StationSummary]:
    """좌표가 속한 **시군구 전체**의 충전소 목록 (경로와 무관한 지역 탐색).

    시군구 코드를 프런트에서 받지 않고 좌표에서 역산하는 이유: 전국 시군구 코드표를
    앱에 심으면 행정구역 개편 때마다 죽는다(강원 42 → 51처럼). 좌표 → 코드 변환은
    이미 경로계획에서 쓰는 카카오 coord2regioncode를 그대로 재사용한다.

    필터 중 fast_only/open_only/min_kw는 카탈로그만으로 판정되어 추가 외부 호출이
    없다. with_status만 실시간 상태 조회(20초 캐시)를 한 번 더 탄다.
    """
    code = await kakao.region_code(LatLng(lat=lat, lng=lng))
    if not code or len(code) < 5:
        raise HTTPException(status_code=400, detail="지역을 확인할 수 없습니다.")

    stations = await ev_stations.stations_in_district(
        code[:2], code[:5], with_status=with_status
    )
    out = [
        s
        for s in stations
        if (not open_only or s.public_access)
        and (not fast_only or "급속" in s.charger_types)
        and s.max_power_kw >= min_kw
    ]
    if with_status:
        out = [s for s in out if s.available]
    return out


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
