"""충전 지점 계산 로직 (BYD 돌핀 스탠다드 기준).

PPT 기획 2번: "현충전량을 출발지·도착지 사이에 충전소 충전건수를 계산".

계산은 두 단계로 구성된다.
  1) 단순 계산 : 주행거리 · 현충전량만으로 필요한 충전 횟수를 산출.
  2) 충전소 매핑 : 실제 충전소 위치를 고려해 각 충전 예상 지점을
                   경로상 가장 가까운(그 지점 이전의) 충전소에 배정.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import ChargePoint, LatLng, StationSummary


@dataclass(frozen=True)
class VehicleSpec:
    name: str
    range_km: float       # 완충(100%) 시 기준(정격) 주행거리
    reserve_pct: float    # 주행 중/도착 시 유지할 최소 잔량(안전 마진)
    charge_to_pct: float  # 충전 1회당 목표 충전량 (급속 기준, greedy용)
    capacity_kwh: float   # 배터리 용량 (충전 시간 계산용)


# BYD 돌핀 스탠다드 (2026 국내 출시) — BYD코리아 공식 제원 기준.
#   배터리 49.92kWh (LFP 블레이드, 사용가능 용량. 총용량 55.6kWh로 표기된 자료도 있음)
#   환경부 인증 1회충전 주행거리 307km, 전비 복합 5.5 / 도심 6.0 / 고속 4.9 km/kWh
#
# range_km=300은 '기준속도(60km/h)·온화' 조건의 정격이다. 인증 307km보다 약간 보수적으로
# 잡아, 기준소비 = 49920/300 ≈ 166Wh/km 가 된다. 이는 환경부 복합 인증을 배터리 기준으로
# 환산한 값(≈164Wh/km, 충전손실 10% 제외)과 거의 일치해 실제 인증치와 정합한다.
# 여기서 온도·속도·도로유형으로 derating 한다.
DOLPHIN_STANDARD = VehicleSpec(
    name="BYD 돌핀 스탠다드",
    range_km=300.0,
    reserve_pct=10.0,
    charge_to_pct=80.0,
    capacity_kwh=49.92,
)

# --- 충전 커브: SoC(%) → 차량이 수용하는 최대 출력(kW) ---------------------
# BYD 돌핀 스탠다드(LFP Blade 49.92kWh) 급속충전 근사. 실측 앵커로 보정했다.
#   · BYD코리아 공식: 30→80% 약 30분  (= 24.96kWh / 0.5h ≈ 평균 50kW)
#   · EVKX 실측(국제형 44.9kWh): 10→80% 38.5분, 평균 49kW, 피크 65kW
# 이 커브는 30→80% 31.0분 / 10→80% 40.7분을 산출해 두 앵커 사이에 들어오며,
# 공식값보다 살짝 길게(보수적으로) 잡아 계획 시간이 부족해지지 않게 한다.
# 실제 충전시간 = Σ (1%당 에너지 / min(충전기kW, 차량커브kW) / 효율).
_CHARGE_CURVE: list[tuple[float, float]] = [
    (0.0, 70.0),
    (30.0, 68.0),
    (40.0, 64.0),
    (50.0, 60.0),
    (60.0, 54.0),
    (70.0, 46.0),
    (80.0, 35.0),
    (90.0, 20.0),
    (100.0, 10.0),
]
_CHARGE_EFF = 0.9  # 충전 효율
# 정지당 고정 오버헤드(분): 고속도로 진출입·주차·플러그·결제 등. 정지 남발 방지.
_STOP_OVERHEAD_MIN = 12.0

# --- 고속도로 본선 vs IC 진출 충전소 -----------------------------------------
# 휴게소 충전소는 고속도로 '본선 위'라 톨게이트 진출 없이 바로 충전한다.
# 그 외(시내·IC 밖) 충전소는 직선거리(투영 이탈km)가 작아도 실제로는 IC로
# 빠져나갔다 재진입해야 해 시간·에너지 손실이 크다. 그래서 주행가능거리가
# 넉넉한 동안은 휴게소를 우선하고, 도달 가능한 휴게소가 없을(한계치) 때에만
# 진출 충전소를 쓰도록 DP 비용에 진출입 패널티를 준다.
_HIGHWAY_STOP_KW = ("휴게소",)
_TOLL_EXIT_PENALTY_MIN = 20.0  # IC 진출입(왕복 주행+지체) 근사 패널티(분)


def _is_highway_stop(name: str) -> bool:
    """고속도로 본선(휴게소) 충전소 여부 — 톨게이트 진출 불필요."""
    return any(k in (name or "") for k in _HIGHWAY_STOP_KW)


def _vehicle_kw(soc: float) -> float:
    """SoC(%)에서 차량이 수용하는 출력(kW) — 커브 선형보간."""
    pts = _CHARGE_CURVE
    if soc <= pts[0][0]:
        return pts[0][1]
    if soc >= pts[-1][0]:
        return pts[-1][1]
    for (s0, k0), (s1, k1) in zip(pts, pts[1:]):
        if s0 <= soc <= s1:
            return k0 + (k1 - k0) * (soc - s0) / (s1 - s0)
    return pts[-1][1]


def _charge_minutes(
    from_soc: float, to_soc: float, charger_kw: float, capacity_kwh: float
) -> float:
    """from_soc→to_soc 충전 소요(분). 충전기 출력과 차량 커브 중 낮은 값 적용."""
    if to_soc <= from_soc:
        return 0.0
    hours = 0.0
    x = from_soc
    while x < to_soc:
        power = min(charger_kw, _vehicle_kw(x))
        if power <= 0:
            return float("inf")
        hours += (capacity_kwh * 0.01) / (power * _CHARGE_EFF)  # 1%분
        x += 1.0
    return hours * 60.0

# --- 외부환경(온도·속도) 주행거리 보정 계수 --------------------------------
# 온도 보정: Geotab(500만 트립)·AAA 실측 앵커의 선형보간.
#   Geotab: 10~31°C 정격 유지, -15°C→54%. AAA: -6.7°C(20°F)→약 -39%.
#
# 참고: 환경부 저온 인증은 이보다 낙관적이다(돌핀 액티브 저온 282 / 상온 354 = 0.80 @-7°C,
# 여기 앵커는 0.61). 인증은 예열된 차량으로 짧은 표준 사이클을 도는 시험이라, 장시간 히터를
# 켜고 달리는 실제 겨울 주행보다 손실이 작게 나온다. 충전계획은 거리를 과대평가하면 방전
# 위험이 있으므로 실측(Geotab/AAA) 기준의 보수적 앵커를 유지한다.
#   여름(냉방): AAA 실측 35°C(95°F)+에어컨 = -17%, Geotab 30~32°C ≈ -5%.
#   기존 앵커는 31°C를 손실 0%로 봐서 한국 여름(에어컨 상시)을 과소반영했다 →
#   Geotab(완만)과 AAA(보수) 사이에서 안전 쪽으로 잡았다.
_TEMP_ANCHORS: list[tuple[float, float]] = [
    (-20.0, 0.50),
    (-15.0, 0.54),
    (-7.0, 0.61),
    (0.0, 0.80),
    (10.0, 1.00),
    (24.0, 1.00),  # 냉난방이 거의 필요 없는 구간
    (31.0, 0.94),  # 에어컨 상시 가동 (Geotab ~5%)
    (35.0, 0.85),  # AAA -17%와 Geotab 사이, 보수 쪽
    (40.0, 0.78),
]
# 속도 보정: 공기저항 ∝ 속도²(Geotab). 소비 E(v) ∝ 1 + k·v².
#   k는 Geotab 실측(50→70km/h 에너지 +13%)로 보정, 정격속도 60km/h 기준.
_REF_SPEED_KMH = 60.0
_AERO_K = 6.3e-5
# 상시 보조부하(kW): 전장·12V·팬·기본 공조 등 시동만 걸려 있으면 드는 전력. 온도와
# 무관하며 '시간기반'이라 소비를 1/속도로 환산 → 정차·정체(저속)에서 지배적. 이게
# 있어야 온화한 날씨의 장시간 정체도 배터리를 정확히 소모한다(휴가철 강원 상습정체).
_AUX_BASE_KW = 0.6
_V_FLOOR = 3.0  # 정체 대비 속도 하한(0 나눗셈·발산 방지)
# 온도 페널티(저온 난방·고온 냉방 추가소비)를 두 성분으로 분리하는 비율.
#   - 시간기반(HVAC 공조): 실내 난방/냉방은 시간당 전력 → 저속에서 per-km 급증(∝1/속도)
#   - 거리기반(배터리 저온저항·회생저하): 주행거리에 비례(속도 무관)
# 페널티를 100% 시간기반으로 두면 '겨울 고속도로 소비 ≈ 겨울 일반도로 소비'로 수렴해
# 고속 공기저항 페널티가 사라지고 → 고속 유효거리를 과대평가(=방전 위험) 한다.
# 거리기반 성분을 분리하면 고속 주행의 온도 페널티가 유지된다. 값을 낮출수록 고속
# 겨울 소비가 커져 더 보수적(안전).  ponytail: 실측(Idaho NL/Geotab 계열) 확보 시 재보정.
_TEMP_HVAC_FRAC = 0.5
# 일반도로 회생제동 상쇄계수: 도심 stop-go는 감속 에너지를 일부 회수 → 견인소비↓.
_REGEN_LOCAL = 0.93  # 일반도로 견인소비 약 7% 절감(고속도로=1.0, 회생 거의 없음)
# 자유주행(정체 없음) 대표속도 — 정체 추가소비(coefficient) 산정 기준
_HIGHWAY_FREEFLOW_KMH = 100.0
_LOCAL_FREEFLOW_KMH = 60.0


def temp_factor(temp_c: float) -> float:
    """기온(°C) → 주행거리 보정계수 (앵커 선형보간, 범위 밖은 클램프)."""
    anchors = _TEMP_ANCHORS
    if temp_c <= anchors[0][0]:
        return anchors[0][1]
    if temp_c >= anchors[-1][0]:
        return anchors[-1][1]
    for (t0, f0), (t1, f1) in zip(anchors, anchors[1:]):
        if t0 <= temp_c <= t1:
            return f0 + (f1 - f0) * (temp_c - t0) / (t1 - t0)
    return 1.0


def speed_factor(speed_kmh: float) -> float:
    """평균속도(km/h) → 주행거리 보정계수 (공기저항 모델, 정격속도 대비)."""
    v = max(speed_kmh, 1.0)
    f = (1 + _AERO_K * _REF_SPEED_KMH**2) / (1 + _AERO_K * v**2)
    return max(0.5, min(1.15, f))


def consumption_wh_per_km(
    speed_kmh: float,
    temp_c: float,
    is_highway: bool,
    capacity_kwh: float,
    nominal_km: float,
) -> float:
    """도로 한 구간의 소비전력(Wh/km) 예측.

    기준소비(정격기준, 60km/h·온화) 위에 네 성분을 물리적으로 분리해 얹는다.
      1) 견인(공기저항 v²): traction_ref / speed_factor(v), 일반도로는 회생 상쇄
      2) 상시 보조부하: baseline kW 시간기반(∝1/속도)
      3) 온도-공조(HVAC): 온도 페널티의 시간기반 몫(∝1/속도, 저속↑)
      4) 온도-배터리: 온도 페널티의 거리기반 몫(속도 무관) — 고속에서도 페널티 유지

    온도 페널티 전량을 3)에만 실으면 겨울 고속소비가 저속소비에 수렴해 고속
    유효거리를 과대평가(방전 위험)한다. _TEMP_HVAC_FRAC로 3)/4)를 나눠 보수화한다.
    기준속도(60km/h)에서는 3)+4)의 합이 페널티 전체와 같아 온도앵커 보정이 보존된다.
    """
    v = max(speed_kmh, _V_FLOOR)
    base = capacity_kwh * 1000.0 / nominal_km  # 총 기준소비(≈150Wh/km @60km/h·온화)
    aux_ref = _AUX_BASE_KW * 1000.0 / _REF_SPEED_KMH  # 기준속도에서 보조부하 몫(~10)
    traction_ref = max(0.0, base - aux_ref)  # 견인 몫 @기준(~140)
    tf = temp_factor(temp_c)
    penalty = base * (1.0 / tf - 1.0) if tf > 0 else 0.0  # 온도 추가소비(Wh/km @기준속도)

    traction = traction_ref / speed_factor(v)  # 주행저항(속도의존, 공기저항 v²)
    if not is_highway:
        traction *= _REGEN_LOCAL  # 도심 회생 상쇄
    aux = _AUX_BASE_KW * 1000.0 / v  # 상시 보조부하(시간기반)
    # 온도 페널티: 시간기반(HVAC, ∝1/속도) + 거리기반(배터리·회생저하, 속도무관)
    hvac = _TEMP_HVAC_FRAC * penalty * _REF_SPEED_KMH / v
    batt = (1.0 - _TEMP_HVAC_FRAC) * penalty
    return traction + aux + hvac + batt


def effective_range_from_segments(
    nominal_km: float,
    capacity_kwh: float,
    temp_c: float,
    segments: list[tuple[float, float, bool]],
) -> tuple[float, float, float]:
    """구간별(거리·실제속도·고속도로여부) 소비를 적산해 유효 주행거리 산출.

    segments: [(distance_km, speed_kmh, is_highway), ...] (카카오 도로별)
    총 소비에너지 = Σ 거리·소비(Wh/km) → 유효거리 = 배터리용량 / 평균소비.

    Returns: (effective_range_km, f_temp, f_speed_equiv)
      f_speed_equiv = 유효거리 / (정격 × 온도계수) — 화면 표시용 등가 속도계수.
    """
    ft = temp_factor(temp_c)
    total_km = sum(d for d, _, _ in segments)
    if total_km <= 0:
        return nominal_km * ft, ft, 1.0
    total_wh = sum(
        d * consumption_wh_per_km(v, temp_c, hw, capacity_kwh, nominal_km)
        for d, v, hw in segments
    )
    eff = capacity_kwh * 1000.0 / (total_wh / total_km) if total_wh > 0 else nominal_km
    fs_equiv = eff / (nominal_km * ft) if nominal_km * ft > 0 else 1.0
    return eff, ft, fs_equiv


def congestion_extra_kwh(
    stretches: list[tuple[float, float, bool]],
    temp_c: float,
    capacity_kwh: float,
    nominal_km: float,
) -> float:
    """정체·지체 구간이 자유주행 대비 '추가로' 쓰는 에너지(kWh).

    stretches: [(distance_km, congestion_speed_kmh, is_highway), ...]
    구간별 추가소비 = (정체속도 소비 − 자유주행속도 소비)·거리. 저속일수록 시간기반
    보조부하(공조·전장)가 커져 급증 → '정체 속도·거리에 대한 계수'의 정량 결과.
    """
    extra = 0.0
    for km, speed, hw in stretches:
        free = _HIGHWAY_FREEFLOW_KMH if hw else _LOCAL_FREEFLOW_KMH
        now = consumption_wh_per_km(speed, temp_c, hw, capacity_kwh, nominal_km)
        base = consumption_wh_per_km(free, temp_c, hw, capacity_kwh, nominal_km)
        extra += max(0.0, now - base) * km
    return round(extra / 1000.0, 2)


# 주행안정성: 안전마진의 '절대거리' 하한. reserve_pct(10%)는 유효거리가 큰 여름엔
# 30km+지만, 겨울·정체로 유효거리가 160km로 줄면 실제 16km밖에 안 돼 방전위험이다.
# 각 충전소·목적지 도착 시 최소 이 거리만큼은 남기도록 reserve를 상향한다.
_MIN_BUFFER_KM = 25.0

# 목적지 도착 최소 잔량(%). 목적지에 충전소가 있어도 도착 시 실시간으로 사용불가
# (점유·고장)일 수 있으므로, 다른 충전소를 찾아갈 여유로 목적지에서도 이만큼 남긴다.
_DEST_MIN_SOC = 15.0


def _effective_reserve_pct(base_pct: float, effective_range_km: float) -> float:
    """안전마진(%) = max(기본 reserve, 최저 절대거리의 %환산). 도착 여유의 절대 하한."""
    if effective_range_km <= 0:
        return base_pct
    return max(base_pct, _MIN_BUFFER_KM / effective_range_km * 100.0)


def recommend_charging_stops(
    path: list[LatLng],
    current_charge_pct: float,
    effective_range_km: float,
    stations: list[StationSummary],
    spec: VehicleSpec = DOLPHIN_STANDARD,
    detour_km: float = 8.0,
) -> tuple[list[ChargePoint], float, bool]:
    """경로 기반 충전소 추천 — greedy 최대 도달가능 알고리즘.

    (ABRP·Tesla 등 EV 경로 플래너의 표준 접근) 출발지 SoC로 도달 가능한 범위
    안에서 '가장 멀리 갈 수 있는' 실제 충전소를 골라 충전하고, 그 지점에서 다시
    도달 범위를 계산하는 과정을 목적지까지 반복한다. 각 단계마다 다음 충전소/
    목적지에 실제로 도달 가능함을 보장하므로, 고정 간격식의 결함(도달 불가한
    지점 추천)을 없앤다. 급속 충전기를 우선(충전시간↓), 이탈거리 짧은 곳을 선호.

    Returns:
        charge_points: 추천 충전소 목록(순서·거리·충전소)
        usable_now_km: 현충전량으로 안전마진 전까지 갈 수 있는 거리
        feasible: 경로상 충전 인프라로 목적지까지 완주 가능 여부
    """
    cum = cumulative_distances(path)
    total = cum[-1]
    km_per_pct = effective_range_km / 100.0
    reserve = _effective_reserve_pct(spec.reserve_pct, effective_range_km)  # 절대거리 하한 반영
    usable_now = max(0.0, (current_charge_pct - reserve) * km_per_pct)
    range_after_charge = max(0.0, (spec.charge_to_pct - reserve) * km_per_pct)

    projected = _project_stations(path, stations, detour_km)

    result: list[ChargePoint] = []
    used: set[str] = set()
    pos = 0.0
    range_left = usable_now
    order = 1
    feasible = True
    # 목적지도 도착 시 충전소가 실시간 사용불가일 수 있어 최소 _DEST_MIN_SOC를 남긴다.
    # (reserve보다 더 보수적 → 음수 slack으로 목적지 도달 조건을 그만큼 앞당김)
    dest_floor = max(reserve, _DEST_MIN_SOC)
    dest_slack = -((dest_floor - reserve) * km_per_pct)

    while pos + range_left + dest_slack < total - 1e-6:
        # 현재 위치·잔여거리로 도달 가능한(진행방향, 이탈거리 포함) 충전소
        cands = [
            (c, o, s)
            for (c, o, s) in projected
            if s.id not in used
            and c > pos + 1e-6
            and (c - pos) + o <= range_left + 1e-6
        ]
        if not cands:
            feasible = False  # 도달 가능한 충전소 없음 → 완주 불가
            break
        c, o, s = _pick_station(cands)
        used.add(s.id)
        result.append(
            ChargePoint(
                order=order,
                distance_from_origin_km=round(c, 1),
                station_id=s.id,
                station_name=s.name,
                location=s.location,
            )
        )
        pos = c
        range_left = max(0.0, range_after_charge - o)  # 경로 복귀분 차감
        order += 1
        if range_after_charge <= 0 or order > 50:
            feasible = pos + range_left + dest_slack >= total - 1e-6
            break

    return result, round(usable_now, 1), feasible


# 출발지 근처 선충전 권장: 1차 충전소 도달 안전마진 계수
_PRECHARGE_TRAFFIC_MARGIN = 0.15  # 1차까지 정체로 추가 소모될 여지(거리 15% 가산)
_PRECHARGE_FALLBACK_KM = 8.0      # 1차 현장 사용불가 시 인근 대체소까지 추가 도달 여유(km)


def origin_precharge_advice(
    current_charge_pct: float,
    effective_range_km: float,
    target_km: float,
    target_unavailable: bool = False,
    is_destination: bool = False,
    spec: VehicleSpec = DOLPHIN_STANDARD,
    traffic_margin: float = _PRECHARGE_TRAFFIC_MARGIN,
    fallback_km: float = _PRECHARGE_FALLBACK_KM,
) -> tuple[int, str] | None:
    """다음 목표지점 도달 안전마진이 부족하면 출발지 근처 권장 충전%를 산출.

    목표지점은 두 가지다.
      * 1차 충전소 (is_destination=False): 도착 후 충전하므로 하한은 reserve.
        위험 두 가지(독립적)에 대비해 더 큰 도달거리를 요구(합산 아님).
          1) 정체: 예측보다 더 소모 → target × (1+traffic_margin)
          2) 현장 사용불가: 인근 대체소까지 → target + fallback_km
      * 목적지 직행 (is_destination=True): 경로상 충전이 필요 없는 짧은 구간이라도
        도착 시 _DEST_MIN_SOC(15%)는 남아야 한다(목적지 충전소가 점유·고장일 수 있고,
        도착 후 다시 움직일 여유도 필요). 하한이 이미 큰 여유이므로 정체마진만 얹는다.

    현 충전량이 필요량보다 낮으면 (권장%, 사유)를 돌려준다. 충분하면 None.
    """
    if effective_range_km <= 0 or target_km <= 0:
        return None

    if is_destination:
        floor = max(spec.reserve_pct, _DEST_MIN_SOC)
        d_req = target_km * (1.0 + traffic_margin)
    else:
        floor = spec.reserve_pct
        # 두 위험은 동시 발생을 가정하지 않으므로 각 필요거리의 max (합산 시 과다권장).
        d_req = max(target_km * (1.0 + traffic_margin), target_km + fallback_km)

    req_pct = floor + d_req / effective_range_km * 100.0
    required = min(100, math.ceil(req_pct))
    if current_charge_pct >= required:
        return None  # 현 충전량으로 안전마진 충분

    if is_destination:
        reason = (
            f"경로상 충전 없이 목적지({target_km:.0f}km)까지 가지만, 도착 시 최소 "
            f"{_DEST_MIN_SOC:.0f}% 잔량 확보를 위해 출발지 근처에서 {required}% 이상 "
            f"충전을 권장합니다."
        )
    elif target_unavailable:
        reason = (
            f"1차 충전소가 현재 사용불가입니다. 대체 충전소까지 여유가 필요하니 "
            f"출발지 근처에서 {required}% 이상 충전을 권장합니다."
        )
    else:
        reason = (
            f"1차 충전소({target_km:.0f}km)까지 정체·현장 사용불가에 대비해 "
            f"출발지 근처에서 {required}% 이상 충전을 권장합니다."
        )
    return required, reason


def _pick_station(
    cands: list[tuple[float, float, StationSummary]],
) -> tuple[float, float, StationSummary]:
    """도달 가능 후보 중 최원거리 우선, 그 부근(15km)에서 휴게소·급속·근접을 선호."""
    max_c = max(c for c, _, _ in cands)
    band = [t for t in cands if t[0] >= max_c - 15.0]
    # 휴게소(본선) 우선 → 급속 우선 → 이탈거리 작은 순
    band.sort(
        key=lambda t: (
            not _is_highway_stop(t[2].name),
            "급속" not in t[2].charger_types,
            t[1],
        )
    )
    return band[0]


def bbox_deg(radius_km: float, lat_deg: float = 36.5) -> tuple[float, float]:
    """반경(km) → (위도차, 경도차) 상한. haversine 전 사각박스 프리필터용.

    삼각함수 없이 뺄셈·비교만으로 '확실히 먼' 후보를 걷어내 근접 탐색을 크게 줄인다.
    경도는 위도에 따라 좁아지므로 한반도 중위도(36.5°)를 기준으로 보수적으로 계산한다.
    """
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat_deg))))
    return dlat, dlng


def _haversine_km(a: LatLng, b: LatLng) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = math.radians(b.lat - a.lat)
    dl = math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def cumulative_distances(path: list[LatLng]) -> list[float]:
    """경로 좌표열의 각 지점까지 누적거리(km)."""
    acc = [0.0]
    for i in range(1, len(path)):
        acc.append(acc[-1] + _haversine_km(path[i - 1], path[i]))
    return acc


def sample_path_points(path: list[LatLng], step_km: float) -> list[LatLng]:
    """경로를 '거리 기준'으로 step_km 간격 샘플링한 좌표 목록.

    정점 인덱스 기준 샘플링(::n)은 고속도로 직선구간에서 정점이 드물어 큰
    거리 공백이 생긴다 → 거리 기준으로 균일 샘플해 공백을 없앤다.
    """
    if not path:
        return []
    cum = cumulative_distances(path)
    pts = [path[0]]
    last = cum[0]
    for pt, c in zip(path, cum):
        if c - last >= step_km:
            pts.append(pt)
            last = c
    if pts[-1] is not path[-1]:
        pts.append(path[-1])
    return pts


def _project_stations(
    path: list[LatLng], stations: list[StationSummary], detour_km: float,
    sample_km: float = 2.0,
) -> list[tuple[float, float, StationSummary]]:
    """각 충전소를 경로에 투영 → (경로누적km, 이탈km, station). detour 이내만, 거리순.

    샘플은 '거리 기준'으로 뽑는다. 정점 인덱스 기준(::step)은 고속도로 직선구간에서
    정점이 드물어 누적거리 간격이 크게 벌어지고, 중간 충전소가 엉뚱한 지점(예: 0km)에
    투영되는 버그가 있었다.
    """
    cum = cumulative_distances(path)
    spath: list[LatLng] = [path[0]]
    scum: list[float] = [cum[0]]
    last = cum[0]
    for pt, c in zip(path, cum):
        if c - last >= sample_km:
            spath.append(pt)
            scum.append(c)
            last = c
    if scum[-1] != cum[-1]:
        spath.append(path[-1])
        scum.append(cum[-1])

    # 사각박스 프리필터: detour 밖이 확실한 지점은 haversine 없이 건너뛴다.
    # (충전소 수천 개 × 샘플 수백 개 완전탐색이 초 단위로 느려지는 것을 막음)
    dlat, dlng = bbox_deg(detour_km)
    out: list[tuple[float, float, StationSummary]] = []
    for st in stations:
        best_d, best_c = float("inf"), 0.0
        slat, slng = st.location.lat, st.location.lng
        for pt, c in zip(spath, scum):
            if abs(pt.lat - slat) > dlat or abs(pt.lng - slng) > dlng:
                continue
            d = _haversine_km(pt, st.location)
            if d < best_d:
                best_d, best_c = d, c
        if best_d <= detour_km:
            out.append((best_c, best_d, st))
    out.sort(key=lambda x: x[0])
    return out


def _select_candidates(
    projected: list[tuple[float, float, StationSummary]],
    seg_km: float = 20.0,
    per_seg: int = 2,
) -> list[tuple[float, float, StationSummary]]:
    """DP 후보 축소: 경로를 seg_km 구간으로 나눠 구간별 상위 per_seg개.

    구간마다 휴게소(본선) 충전소를 우선 포함하고(그다음 고출력·근접), IC 진출
    충전소는 폴백으로 남긴다 → 도달범위가 한계일 때만 DP가 진출 충전소를 쓴다.
    """
    buckets: dict[int, list[tuple[float, float, StationSummary]]] = {}
    for c, o, s in projected:
        buckets.setdefault(int(c // seg_km), []).append((c, o, s))
    out: list[tuple[float, float, StationSummary]] = []
    for k in sorted(buckets):
        items = buckets[k]
        # 휴게소 우선 → 고출력 → 근접 순
        items.sort(
            key=lambda t: (not _is_highway_stop(t[2].name), -t[2].max_power_kw, t[1])
        )
        out.extend(items[:per_seg])
    out.sort(key=lambda t: t[0])
    return out


def plan_charging_dp(
    path: list[LatLng],
    current_charge_pct: float,
    effective_range_km: float,
    avg_speed_kmh: float,
    stations: list[StationSummary],
    spec: VehicleSpec = DOLPHIN_STANDARD,
    detour_km: float = 8.0,
    soc_step: int = 5,
) -> tuple[list[ChargePoint], float, bool, float]:
    """충전 커브 기반 시간최적화(DP).

    총 소요시간(주행+충전)을 최소화하도록 '어느 충전소에 · 몇 %까지' 충전할지
    동적계획법으로 결정한다. 충전시간은 SoC별 충전커브(taper)를 반영하므로,
    고SoC 과충전을 피하고 필요한 만큼만 부분충전하는 계획이 나온다.

    상태 dp[node][soc] = 해당 노드에 해당 SoC로 도착하는 최소 시간(분).
    노드: 출발지(0) · 후보 충전소(경로순) · 목적지. 인접 노드로만 전이(통과 허용).

    Returns: (charge_points, usable_now_km, feasible, total_charge_min)
    """
    cum = cumulative_distances(path)
    total = cum[-1]
    km_per_pct = effective_range_km / 100.0
    cap = spec.capacity_kwh
    reserve = _effective_reserve_pct(spec.reserve_pct, effective_range_km)  # 절대거리 하한 반영
    dest_floor = max(reserve, _DEST_MIN_SOC)  # 목적지 도착 최소 잔량(실시간 사용불가 대비)
    v = max(avg_speed_kmh, 1.0)

    def cons_pct(km: float) -> float:
        return km / effective_range_km * 100.0 if effective_range_km > 0 else 999.0

    def drive_min(km: float) -> float:
        return km / v * 60.0

    cands = _select_candidates(_project_stations(path, stations, detour_km))
    # 출발지·목적지 근처(±2km)는 충전 '정지'로 부적절 → 제외
    cands = [(c, o, s) for (c, o, s) in cands if 2.0 < c < total - 2.0]
    nodes: list[tuple[float, float, StationSummary | None]] = (
        [(0.0, 0.0, None)] + [(c, o, s) for c, o, s in cands] + [(total, 0.0, None)]
    )
    n = len(nodes)

    # SoC 격자는 0부터 만든다. reserve부터 시작하면 '현충전량 5%'처럼 안전마진보다
    # 낮은 출발 상태가 reserve(10%)로 올려붙어 실제보다 낙관적인 계획이 나온다.
    # 격자를 0까지 두면 출발 SoC를 있는 그대로 표현하고, 출발 제약(dep_route >= reserve)이
    # 자연히 '이 상태로는 안전하게 출발 불가 → infeasible'을 만들어 선충전 안내로 이어진다.
    socs = list(range(0, 101, soc_step))
    if socs[-1] != 100:
        socs.append(100)
    b = len(socs)

    def snap(soc: float) -> int:
        """SoC → 버킷 인덱스(보수적으로 내림)."""
        val = max(0.0, min(100.0, soc))
        best = 0
        for i, s in enumerate(socs):
            if s <= val + 1e-9:
                best = i
        return best

    INF = float("inf")
    dp = [[INF] * b for _ in range(n)]
    par: list[list[tuple[int, int, int] | None]] = [[None] * b for _ in range(n)]
    dp[0][snap(current_charge_pct)] = 0.0

    # 전 구간 쌍(all-pairs) 전이: 노드 i에서 (선택적 충전 후) 도달 가능한 j로 직행.
    # 정지 지점에서만 SoC 이산화가 일어나 누적 오차를 최소화한다.
    for i in range(n):
        pos_i, off_i, st_i = nodes[i]
        chargeable = st_i is not None
        power_i = st_i.max_power_kw if st_i else 0.0
        # IC 진출 충전소면 진출입 패널티(선택 편향용; 실제 표시시간엔 미포함)
        exit_penalty = (
            0.0 if (st_i is None or _is_highway_stop(st_i.name)) else _TOLL_EXIT_PENALTY_MIN
        )
        for ai in range(b):
            base = dp[i][ai]
            if base == INF:
                continue
            a_soc = socs[ai]
            dep_list = range(ai, b) if chargeable else [ai]
            for bi in dep_list:
                d_soc = socs[bi]
                if d_soc > a_soc:  # 충전: 순수충전시간 + 정지 오버헤드 + 우회 + 진출입
                    ct = (
                        _charge_minutes(a_soc, d_soc, power_i, cap)
                        + _STOP_OVERHEAD_MIN
                        + 2 * off_i / v * 60.0
                        + exit_penalty
                    )
                    dep_route = d_soc - cons_pct(2 * off_i)
                else:  # 통과(무충전)
                    ct = 0.0
                    dep_route = a_soc
                if dep_route < reserve - 1e-9:
                    continue
                base_range_km = (dep_route - reserve) * km_per_pct
                # 목적지도 도착 시 충전소가 실시간 사용불가일 수 있어 최소 dest_floor(15%)를 남긴다
                dest_range_km = (dep_route - dest_floor) * km_per_pct
                for j in range(i + 1, n):
                    gap = nodes[j][0] - pos_i
                    limit = dest_range_km if j == n - 1 else base_range_km
                    if gap > limit + 1e-6:
                        continue  # 이 j는 도달 불가 (노드 수가 적어 break 대신 continue)
                    arrive = dep_route - cons_pct(gap)
                    aj = snap(max(arrive, float(reserve)))
                    cost = base + ct + drive_min(gap)
                    if cost < dp[j][aj]:
                        dp[j][aj] = cost
                        par[j][aj] = (i, ai, bi)

    dest = n - 1
    best, best_idx = INF, -1
    for si in range(b):
        if dp[dest][si] < best:
            best, best_idx = dp[dest][si], si

    usable_now = round(max(0.0, (current_charge_pct - reserve) * km_per_pct), 1)
    if best == INF:
        return [], usable_now, False, 0.0

    # 역추적: 충전(b>a)이 일어난 노드 수집
    charges: list[tuple[int, float, float]] = []
    ci, si = dest, best_idx
    while par[ci][si] is not None:
        pi, pai, pbi = par[ci][si]
        a_soc, d_soc = socs[pai], socs[pbi]
        if d_soc > a_soc:
            charges.append((pi, a_soc, d_soc))
        ci, si = pi, pai
    charges.reverse()

    result: list[ChargePoint] = []
    pure_charge_min = 0.0
    for order, (ni, a_soc, d_soc) in enumerate(charges, start=1):
        pos, off, st = nodes[ni]
        assert st is not None
        cm = _charge_minutes(a_soc, d_soc, st.max_power_kw, cap)
        pure_charge_min += cm
        result.append(
            ChargePoint(
                order=order,
                distance_from_origin_km=round(pos, 1),
                station_id=st.id,
                station_name=st.name,
                location=st.location,
                charge_from_pct=round(a_soc),
                charge_to_pct=round(d_soc),
                charge_kwh=round(cap * (d_soc - a_soc) / 100.0, 1),
                charge_min=round(cm),
            )
        )
    # 충전·정차 시간 = 순수 충전 + 정지당 오버헤드
    charge_stop_min = pure_charge_min + len(charges) * _STOP_OVERHEAD_MIN
    return result, usable_now, True, round(charge_stop_min, 0)
