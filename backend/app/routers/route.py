"""경로 계획 라우터 — 앱의 핵심 엔드포인트.

이 라우터는 **오케스트레이션만** 담당한다. 실제 계산은 전부 `services/charging.py`
(외부 의존 없는 순수 모듈)에 있고, 외부 조회는 `services/kakao.py` ·
`services/ev_stations.py`가 맡는다.

plan_route()의 처리 순서 (순서 자체가 성능·정확도에 중요하다)
  1. 지오코딩 ×2 → 경로 조회            (Kakao, ~2.3초)
  2. 유효거리·정체 추가소비 산출         (순수계산, ~0)
  3. 경로 인근 충전소 카탈로그            (공공 EV API, 콜드면 ~4.5초 = 전체의 57%)
  4. warm_status()로 시군구 상태 병렬 프리페치
       └ 이후 5·7·8의 상태 조회가 전부 캐시 히트가 되어 순차 대기가 사라진다
  5. 목적지 인근 개방 충전소 탐색
  6. 충전계획 DP → 실패 시 greedy 폴백
  7. 배정 충전소 실시간 상태 + 사용불가 시 대체소
  8. 출발 전 선충전 권장 판정

실측 시간 분해는 docs/04-운영이슈.md [I-S01] 참조.
"""

from fastapi import APIRouter, HTTPException

from ..models import (
    AltStation,
    ChargePoint,
    CongestionStretch,
    DestinationCharging,
    OriginPrecharge,
    RoutePlanRequest,
    RoutePlanResponse,
)
from ..services import ev_stations, kakao
from ..services.charging import (
    DOLPHIN_STANDARD,
    _haversine_km,
    congestion_extra_kwh,
    effective_range_from_segments,
    origin_precharge_advice,
    plan_charging_dp,
    recommend_charging_stops,
)
from ..models import LatLng, StationSummary

router = APIRouter(prefix="/api/route", tags=["route"])


@router.post("/warmup")
async def warmup(req: RoutePlanRequest) -> dict:
    """경로에 필요한 충전소 카탈로그를 미리 데운다(계획은 하지 않는다).

    콜드 상태의 계획 요청은 시군구 20여 곳의 카탈로그를 받느라 대부분의 시간을 쓴다.
    앱을 열 때 이 엔드포인트를 미리 호출해두면, 사용자가 '계산'을 누를 때는 캐시가
    채워져 있어 대기가 크게 줄어든다. 실패해도 계획에는 영향이 없으므로 조용히 무시한다.
    """
    try:
        origin = await kakao.geocode(req.origin)
        dest = await kakao.geocode(req.destination)
        directions = await kakao.get_directions(origin, dest)
        stations = await ev_stations.stations_near_path(directions["path"])
        return {"ok": True, "stations": len(stations)}
    except Exception:
        # 워밍업은 실패해도 무해 — 사용자 요청 흐름을 막지 않는다.
        return {"ok": False, "stations": 0}


@router.post("/plan", response_model=RoutePlanResponse)
async def plan_route(req: RoutePlanRequest) -> RoutePlanResponse:
    """출발지·도착지·현충전량 → 경로 + (외부환경 보정) 충전예상지점수 계산."""
    try:
        origin = await kakao.geocode(req.origin)
        dest = await kakao.geocode(req.destination)
    except kakao.LocationNotFound:
        raise HTTPException(
            status_code=400,
            detail="출발지 또는 도착지를 찾을 수 없습니다. 주소를 다시 입력해 주세요.",
        )

    try:
        directions = await kakao.get_directions(origin, dest)
    except kakao.RouteUnavailable:
        raise HTTPException(
            status_code=502,
            detail="실제 도로 경로를 조회하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )
    path = directions["path"]
    distance_km = directions["distance_km"]
    duration_min = directions["duration_min"]

    # 평균속도 = 거리 / 소요시간 → 주행시간 계산용(실제 교통 반영)
    avg_speed = distance_km / (duration_min / 60.0) if duration_min > 0 else 60.0
    # 유효거리 = 도로 구간별(실제속도·고속도로여부) 소비전력 적산 (온도·속도·회생 반영)
    highway_km = directions.get("highway_km", 0.0)
    local_km = directions.get("local_km", distance_km)
    segments = directions.get("segments") or [(distance_km, avg_speed, False)]
    r_eff, f_temp, f_speed = effective_range_from_segments(
        DOLPHIN_STANDARD.range_km, DOLPHIN_STANDARD.capacity_kwh,
        req.temperature_c, segments,
    )
    # 정체·지체로 인한 자유주행 대비 추가 소비(kWh) + 지도 표시용 구간
    congestion = directions.get("congestion", [])
    extra_kwh = congestion_extra_kwh(
        [(c["distance_km"], c["speed_kmh"], c["is_highway"]) for c in congestion],
        req.temperature_c, DOLPHIN_STANDARD.capacity_kwh, DOLPHIN_STANDARD.range_km,
    )

    stations = await ev_stations.stations_near_path(path)

    # 경로가 지나는 시군구들의 실시간 상태를 병렬로 미리 데운다(중복 시군구 1회,
    # bounded). 이후 목적지·배정·대체 충전소 상태 조회가 모두 캐시 히트가 되어
    # 순차 루프의 네트워크 대기를 제거한다.
    await ev_stations.warm_status(s.id for s in stations)

    # 목적지 인근 '외부인 이용가능' 충전소 탐색.
    # 어울림/아파트 등 거주건물(입주민전용)은 방문객이 못 쓰므로 건너뛰고,
    # 인근(3km) 개방 충전소(고객/공공/시설, 주차비 발생 포함)를 가까운 순으로 찾는다.
    dest_open = None  # (station, reason)
    for s in sorted(
        (s for s in stations if _haversine_km(dest, s.location) <= 3.0),
        key=lambda s: _haversine_km(dest, s.location),
    )[:8]:
        res = await ev_stations.station_availability(s.id)
        if res and res[0]:  # 외부인 이용가능
            dest_open = (s, res[1])
            break
    # 충전 커브 기반 DP 시간최적화 (총 주행+충전 시간 최소, 부분충전 결정).
    # 목적지에 충전소가 있어도 도착 시 실시간 사용불가 대비 최소 15%를 남기도록 계획한다.
    charge_points, usable_now, feasible, charge_min = plan_charging_dp(
        path, req.current_charge_pct, r_eff, avg_speed, stations,
        DOLPHIN_STANDARD,
    )
    plan_method = "dp"
    if not feasible:
        # DP 불가 시 도달가능성 우선 greedy 폴백
        charge_points, usable_now, feasible = recommend_charging_stops(
            path, req.current_charge_pct, r_eff, stations,
            DOLPHIN_STANDARD,
        )
        charge_min, plan_method = 0.0, "greedy"

    # 목적지 충전소 안내 (외부인 이용가능한 것만; 사유/주차비 표기)
    destination_charging = None
    if dest_open is not None:
        destination_charging = DestinationCharging(
            station_id=dest_open[0].id,
            station_name=dest_open[0].name,
            note=dest_open[1],  # "이용 가능" / "외부인 이용가능(주차비 발생)"
        )

    # 배정 충전소 실시간 상태 조회 + 사용불가 시 대체 충전소
    await _enrich_availability(charge_points, stations)

    # 출발지 근처 선충전 권장.
    #   · 경로상 충전이 있으면  → 1차 충전소 도달 안전마진(정체·현장불가) 기준
    #   · 충전 없이 직행이면    → 목적지 도착 최소잔량(15%) 기준
    #     (짧은 구간이라 '충전 0회'로 나와도 도착 잔량이 바닥이면 출발 전 충전이 필요하다)
    if charge_points:
        first = charge_points[0]
        advice = origin_precharge_advice(
            req.current_charge_pct,
            r_eff,
            first.distance_from_origin_km,
            target_unavailable=first.available is False,
        )
    else:
        advice = origin_precharge_advice(
            req.current_charge_pct, r_eff, distance_km, is_destination=True
        )

    origin_precharge = None
    if advice is not None:
        # 권장만 하지 않고 '어디서 충전할지'까지 안내한다 — 출발지 인근에서 외부인이
        # 실제로 쓸 수 있는(입주민·관계자·특정차량 전용 제외) 충전소를 찾는다.
        near_origin = await _find_alternative(origin, stations, set(), radius_km=5.0)
        origin_precharge = OriginPrecharge(
            required_pct=advice[0], reason=advice[1], station=near_origin
        )

    return RoutePlanResponse(
        vehicle=DOLPHIN_STANDARD.name,
        origin=origin,
        destination=dest,
        total_distance_km=distance_km,
        duration_min=duration_min,
        current_charge_pct=req.current_charge_pct,
        initial_range_km=usable_now,
        charge_stops_count=len(charge_points),
        feasible=feasible,
        total_charge_min=int(charge_min),
        total_trip_min=int(duration_min + charge_min),
        plan_method=plan_method,
        destination_charging=destination_charging,
        origin_precharge=origin_precharge,
        nominal_range_km=DOLPHIN_STANDARD.range_km,
        effective_range_km=round(r_eff, 1),
        temperature_c=req.temperature_c,
        avg_speed_kmh=round(avg_speed, 1),
        temp_factor=round(f_temp, 3),
        speed_factor=round(f_speed, 3),
        highway_km=highway_km,
        local_km=local_km,
        jam_km=directions.get("jam_km", 0.0),
        delay_km=directions.get("delay_km", 0.0),
        congestion_extra_kwh=extra_kwh,
        congestion=[CongestionStretch(**c) for c in congestion],
        charge_points=charge_points,
        path=path,
        data_source=directions["source"],
    )


async def _enrich_availability(
    charge_points: list[ChargePoint], near_stations: list[StationSummary]
) -> None:
    """각 배정 충전소의 실시간 상태를 채우고, 사용불가면 대체 충전소를 찾는다."""
    for cp in charge_points:
        if not cp.station_id:
            continue
        res = await ev_stations.station_availability(cp.station_id)
        if res is None:
            continue
        cp.available, cp.status_reason = res
        if not cp.available and cp.location is not None:
            cp.alternative = await _find_alternative(
                cp.location, near_stations, {cp.station_id}
            )


async def _find_alternative(
    loc: LatLng,
    stations: list[StationSummary],
    exclude: set[str],
    radius_km: float = 6.0,
    limit: int = 6,
) -> AltStation | None:
    """지점 인근에서 '사용가능'한 대체 충전소를 찾는다 (가까운 순, 최대 limit개 확인)."""
    cands = sorted(
        (
            s
            for s in stations
            if s.id not in exclude and _haversine_km(loc, s.location) <= radius_km
        ),
        key=lambda s: _haversine_km(loc, s.location),
    )[:limit]
    for s in cands:
        res = await ev_stations.station_availability(s.id)
        if res and res[0]:
            return AltStation(
                station_id=s.id,
                station_name=s.name,
                location=s.location,
                available=True,
                status_reason=res[1],
            )
    return None
