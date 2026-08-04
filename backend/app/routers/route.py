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

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from ..models import (
    AltStation,
    ChargePoint,
    CongestionAlternative,
    CongestionStretch,
    DepartOption,
    DepartOptionsResponse,
    DestinationCharging,
    OriginPrecharge,
    RoutePlanRequest,
    RoutePlanResponse,
    StationCongestion,
)
from ..services import congestion as congestion_svc
from ..services import ev_stations, kakao
from ..services.charging import (
    DOLPHIN_STANDARD,
    _haversine_km,
    apply_cruise_speed,
    congestion_extra_kwh,
    effective_range_from_segments,
    highway_avg_speed,
    origin_precharge_advice,
    plan_charging_dp,
    recommend_charging_stops,
)
from ..models import LatLng, StationSummary

# 동시 실행 상한. ratelimit.py는 '분당' 제한이라 20건이 같은 순간에 들어올 수 있고,
# 그러면 아래 두 가지가 동시에 터진다.
#   · 메모리 — 요청 1건이 시군구 카탈로그 원본 로우를 최대 수백 MB까지 들고 있다.
#              Render 무료는 512MB라 서로 다른 경로 2~3건만 겹쳐도 OOM 위험.
#   · 커넥션 풀 — 공유 풀 20개 중 10개는 이미 _kakao_sem(6)+_fetch_sem(4)에 고정.
#                 남는 10개를 세마포어 없는 directions/geocode가 나눠 쓴다.
# 초과분은 거절하지 않고 여기서 '대기'시킨다. 어차피 외부 API 동시성은 _fetch_sem=4로
# 고정이라 병렬로 밀어 넣어도 총 처리량은 늘지 않는다 — 메모리 피크만 커질 뿐이다.
_PLAN_CONCURRENCY = 2
_plan_sem = asyncio.Semaphore(_PLAN_CONCURRENCY)


async def _limit_concurrency():
    """이 라우터의 핸들러 실행을 _PLAN_CONCURRENCY개로 제한(초과분은 대기).

    yield 의존성이라 핸들러가 끝날 때(예외·취소 포함) 세마포어가 반드시 반환된다.
    plan과 warmup이 같은 세마포어를 쓴다 — 둘의 비용이 사실상 같기 때문이다.
    """
    async with _plan_sem:
        yield


router = APIRouter(
    prefix="/api/route",
    tags=["route"],
    dependencies=[Depends(_limit_concurrency)],
)


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


@dataclass
class _Ctx:
    """경로 계획과 출발시각 추천이 공유하는 준비 결과.

    지오코딩·경로조회·충전소 카탈로그는 출발 시각과 무관하다. 출발시각 추천은
    이걸 한 번만 만들고 DP만 여러 번 돌린다 → 외부 호출이 늘지 않는다.
    """

    origin: LatLng
    dest: LatLng
    directions: dict
    path: list[LatLng]
    distance_km: float
    duration_min: float
    avg_speed: float
    r_eff: float
    f_temp: float
    f_speed: float
    stations: list[StationSummary]
    highway_speed: float | None  # 실제 계산에 쓰인 고속도로·자동차전용 평균속도


async def _prepare(req: RoutePlanRequest) -> _Ctx:
    """지오코딩 → 경로 → 유효거리 → 경로 인근 충전소. (실시간 상태는 데우지 않음)"""
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
    distance_km = directions["distance_km"]
    duration_min = directions["duration_min"]
    # 평균속도 = 거리 / 소요시간 → 주행시간 계산용(실제 교통 반영)
    avg_speed = distance_km / (duration_min / 60.0) if duration_min > 0 else 60.0
    # 유효거리 = 도로 구간별(실제속도·고속도로여부) 소비전력 적산 (온도·속도·회생 반영)
    segments = directions.get("segments") or [(distance_km, avg_speed, "local")]
    # 사용자 순항속도를 고속도로·자동차전용 구간에만 반영한 뒤 소비를 적산한다.
    # 미입력이면 그대로 통과하므로 기존 동작과 동일하다.
    segments = apply_cruise_speed(segments, req.cruise_speed_kmh)
    r_eff, f_temp, f_speed = effective_range_from_segments(
        DOLPHIN_STANDARD.range_km, DOLPHIN_STANDARD.capacity_kwh,
        req.temperature_c, segments,
    )
    stations = await ev_stations.stations_near_path(directions["path"])
    return _Ctx(
        origin=origin, dest=dest, directions=directions, path=directions["path"],
        distance_km=distance_km, duration_min=duration_min, avg_speed=avg_speed,
        r_eff=r_eff, f_temp=f_temp, f_speed=f_speed, stations=stations,
        highway_speed=highway_avg_speed(segments),
    )


def _depart_at(req: RoutePlanRequest) -> datetime:
    """요청의 출발 시각(없으면 지금). 혼잡 예측의 기준 시각이다."""
    if req.depart_at is not None:
        dt = req.depart_at
        # 타임존 없는 값은 KST로 본다(앱이 국내 전용이라 그게 사용자 의도다).
        return dt if dt.tzinfo else dt.replace(tzinfo=congestion_svc.KST)
    return datetime.now(congestion_svc.KST)


@router.post("/plan", response_model=RoutePlanResponse)
async def plan_route(req: RoutePlanRequest) -> RoutePlanResponse:
    """출발지·도착지·현충전량 → 경로 + (외부환경 보정) 충전예상지점수 계산."""
    ctx = await _prepare(req)
    origin, dest = ctx.origin, ctx.dest
    directions = ctx.directions
    path, distance_km, duration_min = ctx.path, ctx.distance_km, ctx.duration_min
    avg_speed, r_eff, f_temp, f_speed = ctx.avg_speed, ctx.r_eff, ctx.f_temp, ctx.f_speed
    stations = ctx.stations
    highway_km = directions.get("highway_km", 0.0)
    local_km = directions.get("local_km", distance_km)

    # 정체·지체로 인한 자유주행 대비 추가 소비(kWh) + 지도 표시용 구간
    congestion = directions.get("congestion", [])
    extra_kwh = congestion_extra_kwh(
        [(c["distance_km"], c["speed_kmh"], c["is_highway"]) for c in congestion],
        req.temperature_c, DOLPHIN_STANDARD.capacity_kwh, DOLPHIN_STANDARD.range_km,
    )

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
    # 성수기 충전 대기 예측을 미리 배치 조회해 DP에 클로저로 주입한다.
    # 데이터가 부족하면 wait_min()이 0을 돌려주므로 기존 고정 오버헤드로 폴백된다.
    depart_at = _depart_at(req)
    wl = await congestion_svc.wait_lookup(
        [s.id for s in stations], depart_at, duration_min
    )

    # 충전 커브 기반 DP 시간최적화 (총 주행+충전 시간 최소, 부분충전 결정).
    # 목적지에 충전소가 있어도 도착 시 실시간 사용불가 대비 최소 15%를 남기도록 계획한다.
    charge_points, usable_now, feasible, charge_min = plan_charging_dp(
        path, req.current_charge_pct, r_eff, avg_speed, stations,
        DOLPHIN_STANDARD, wait_min_fn=wl.wait_min,
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

    # 도착 예정 시각 기준 혼잡 예측을 응답에 싣고, 혼잡 지점을 피한 대안을 계산한다.
    _attach_congestion(charge_points, wl)
    total_wait = sum(
        cp.congestion.wait_min for cp in charge_points if cp.congestion is not None
    )
    congestion_alt = _congestion_alternative(
        ctx, req, charge_points, wl, duration_min + charge_min
    )
    cg_status, cg_days = _congestion_status(wl)

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
        cruise_speed_kmh=req.cruise_speed_kmh,
        highway_speed_kmh=ctx.highway_speed,
        jam_km=directions.get("jam_km", 0.0),
        delay_km=directions.get("delay_km", 0.0),
        congestion_extra_kwh=extra_kwh,
        congestion=[CongestionStretch(**c) for c in congestion],
        charge_points=charge_points,
        path=path,
        data_source=directions["source"],
        congestion_wait_min=int(round(total_wait)) if total_wait > 0 else None,
        congestion_alternative=congestion_alt,
        congestion_status=cg_status,
        congestion_days=cg_days,
    )


# 대안 계획이 이만큼은 줄여야 제시한다. 이보다 작으면 예측 오차 범위 안이라
# 사용자에게 선택지를 늘려줄 뿐 도움이 안 된다.
_ALT_MIN_SAVING_MIN = 10.0
# 출발시각 추천 탐색 범위(시간). ±3시간을 1시간 간격 → 기준 포함 7회 DP.
_DEPART_OFFSETS = (-3, -2, -1, 0, 1, 2, 3)


def _congestion_status(wl) -> tuple[str | None, int | None]:
    """예측 준비 상태 — 이미 받아둔 예측에서 도출한다(추가 쿼리 없음).

    화면이 "기능이 없다"와 "아직 모으는 중"을 구분하지 못하면, 수집 첫 2주 동안
    사용자는 이 기능이 존재하는지조차 알 수 없다. 그래서 진행도를 함께 내려준다.
    """
    preds = list(wl.preds.values())
    if not preds:
        return None, None
    ok = [p for p in preds if p.status == "ok"]
    if ok:
        return "ready", max(p.n_days for p in ok)
    if all(p.status == "unavailable" for p in preds):
        return "off", None
    return "collecting", max((p.n_days for p in preds), default=0)


def _attach_congestion(charge_points: list[ChargePoint], wl) -> None:
    """각 배정 충전소에 도착 예정 시각 기준 혼잡 예측을 붙인다.

    데이터가 부족하거나 DB가 없으면 congestion=None으로 두어 화면에서 빠지게 한다.
    '데이터 부족'을 굳이 표시하지 않는 이유: 아직 수집이 안 된 초기에는 모든
    충전소가 그 상태라 화면이 경고로 도배된다.
    """
    for cp in charge_points:
        if not cp.station_id or cp.arrive_after_min is None:
            continue
        p = wl.at(cp.station_id, cp.arrive_after_min)
        if p is None or p.status != "ok":
            continue
        cp.congestion = StationCongestion(
            level=p.level,
            wait_min=p.wait_min,
            wait_lo=p.wait_lo,
            wait_hi=p.wait_hi,
            confidence=p.confidence,
            n_days=p.n_days,
            daytype_fallback=p.daytype_fallback or None,
        )


def _congestion_alternative(
    ctx: _Ctx,
    req: RoutePlanRequest,
    charge_points: list[ChargePoint],
    wl,
    base_total_min: float,
) -> CongestionAlternative | None:
    """혼잡으로 예측된 충전소를 빼고 한 번 더 계획해 총 시간을 비교한다.

    후보를 하나씩 앞뒤로 바꿔가며 여러 번 돌리지 않고, 혼잡 지점을 한꺼번에
    제외한 계획 1회만 돌린다. DP가 웜 0.4초라 1회는 예산 안이고, 실제로
    사용자가 알고 싶은 것은 "붐비는 데를 피하면 얼마나 빨라지나" 하나다.
    """
    busy = {
        cp.station_id: cp.station_name or cp.station_id
        for cp in charge_points
        if cp.station_id and cp.congestion and cp.congestion.level == "혼잡"
    }
    if not busy:
        return None
    reduced = [s for s in ctx.stations if s.id not in busy]
    if not reduced:
        return None

    alt_points, _, feasible, alt_charge_min = plan_charging_dp(
        ctx.path, req.current_charge_pct, ctx.r_eff, ctx.avg_speed, reduced,
        DOLPHIN_STANDARD, wait_min_fn=wl.wait_min,
    )
    if not feasible:
        return None  # 혼잡해도 그 충전소가 없으면 완주 불가 → 대안이 아니다
    saved = base_total_min - (ctx.duration_min + alt_charge_min)
    if saved < _ALT_MIN_SAVING_MIN:
        return None

    names = [cp.station_name or "" for cp in alt_points]
    return CongestionAlternative(
        saved_min=int(round(saved)),
        total_charge_min=int(round(alt_charge_min)),
        stations=names,
        avoided=list(busy.values()),
        note=f"혼잡 예상 충전소를 피하면 총 소요시간이 약 {int(round(saved))}분 짧아집니다.",
    )


@router.post("/depart-options", response_model=DepartOptionsResponse)
async def depart_options(req: RoutePlanRequest) -> DepartOptionsResponse:
    """같은 경로를 여러 출발 시각으로 시뮬레이션해 총 소요시간을 비교한다.

    경로·충전소 조회는 **1회만** 하고 DP만 7번 돌린다 → 외부 API 호출이 늘지 않는다.

    ⚠ 정체 차이는 반영되지 않는다. 카카오 실시간 교통은 현재 시점만 제공하므로
    미래 출발 시각의 정체를 알 수 없다. 여기서 달라지는 것은 충전 대기뿐이다.
    """
    ctx = await _prepare(req)
    base = _depart_at(req)
    station_ids = [s.id for s in ctx.stations]

    options: list[DepartOption] = []
    for off in _DEPART_OFFSETS:
        depart = base + timedelta(hours=off)
        wl = await congestion_svc.wait_lookup(station_ids, depart, ctx.duration_min)
        points, _, feasible, charge_min = plan_charging_dp(
            ctx.path, req.current_charge_pct, ctx.r_eff, ctx.avg_speed, ctx.stations,
            DOLPHIN_STANDARD, wait_min_fn=wl.wait_min,
        )
        wait = sum(
            wl.wait_min(cp.station_id, cp.arrive_after_min or 0.0)
            for cp in points
            if cp.station_id
        )
        options.append(
            DepartOption(
                offset_h=off,
                depart_at=depart,
                total_trip_min=int(round(ctx.duration_min + charge_min)),
                charge_wait_min=int(round(wait)),
                feasible=feasible,
            )
        )

    usable = [o for o in options if o.feasible]
    baseline = next((o for o in options if o.offset_h == 0), None)
    best = min(usable, key=lambda o: o.total_trip_min) if usable else None
    best_off = (
        best.offset_h
        if best is not None
        and baseline is not None
        and best.offset_h != 0
        and baseline.total_trip_min - best.total_trip_min >= _ALT_MIN_SAVING_MIN
        else None
    )
    return DepartOptionsResponse(
        base_depart_at=base,
        options=options,
        best_offset_h=best_off,
        note="충전 대기 예상치 기준입니다. 도로 정체 변화는 반영되지 않습니다.",
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
