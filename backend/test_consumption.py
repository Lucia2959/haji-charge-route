"""소비모델 자체검증 (프레임워크 없음: python test_consumption.py).

온도 페널티를 시간기반(HVAC)+거리기반(배터리)으로 분리한 뒤의 불변식 확인.
핵심: 겨울 고속도로 소비가 겨울 일반도로 소비보다 확실히 커야 하고(공기저항 유지),
     기준속도에서는 기존 온도앵커 보정이 그대로 보존돼야 한다(보수화가 mild를 안 건드림).
"""
from app.services.charging import (
    consumption_wh_per_km as C,
    temp_factor,
    origin_precharge_advice,
    DOLPHIN_STANDARD as V,
)

CAP, NOM = V.capacity_kwh, V.range_km


def approx(a, b, tol=0.5):
    return abs(a - b) <= tol


# 1) 기준속도(60km/h)·온화(20°)·고속도로(회생無)에서 총소비 = base = cap*1000/nom
base = CAP * 1000.0 / NOM
assert approx(C(60, 20, True, CAP, NOM), base), (
    f"mild@60 고속 기준소비 {C(60,20,True,CAP,NOM):.1f} != base {base:.1f}"
)

# 2) 기준속도에서 온도앵커 보존: 고속60 @온도 == base / temp_factor(온도)
for t in (-15, 0, 20, 35):
    got = C(60, t, True, CAP, NOM)
    want = base / temp_factor(t)
    assert approx(got, want, 0.6), f"@60 {t}°: {got:.1f} != base/tf {want:.1f}"

# 3) 핵심: 겨울(-15°) 고속100 소비 > 일반60 소비 (공기저항 페널티 유지)
hw = C(100, -15, True, CAP, NOM)
lo = C(60, -15, False, CAP, NOM)
assert hw > lo + 15, f"겨울 고속({hw:.1f})이 일반60({lo:.1f})보다 충분히 크지 않음"

# 4) 보수성: 분리 후 겨울 고속100 소비가 '전량 시간기반' 근사보다 크거나 같아야
#    (거리기반 성분이 고속에서 소비를 되살리므로). 수치 하한만 확인.
assert hw > 285, f"겨울 고속100 소비 {hw:.1f} < 285 — 보수화 부족"

# 5) 페널티는 항상 ≥0 (temp_factor ≤ 1) → 어떤 온도에서도 소비가 mild 이상
for t in (-20, -15, 0, 20, 31, 35, 40):
    assert C(100, t, True, CAP, NOM) >= C(100, 20, True, CAP, NOM) - 0.1, f"{t}°"

# 6) 출발지 선충전 권장 — 안전마진 부족 시만 발동, 충분하면 None
import math as _m
#    겨울 마진부족(유효160, 1차65km, 현40%) → 발동해야
adv = origin_precharge_advice(40.0, 160.0, 65.0)
assert adv is not None, "겨울 마진부족인데 권장 안 뜸"
req, reason = adv
assert 40 < req <= 100 and "충전" in reason, f"권장값 이상: {adv}"
#    권장값은 필요거리 공식(두 위험의 max)과 일치: reserve + max(d*1.15, d+8)/eff*100 올림
d_req = max(65.0 * 1.15, 65.0 + 8.0)
want = min(100, _m.ceil(V.reserve_pct + d_req / 160.0 * 100))
assert req == want, f"권장값 {req} != 공식 {want}"
#    1차 사용불가 플래그면 사유 문구가 달라야
adv2 = origin_precharge_advice(40.0, 160.0, 65.0, target_unavailable=True)
assert adv2 and "사용불가" in adv2[1], "사용불가 사유 미반영"
#    오탐 방지(핵심): 먼 1차라도 현 충전량이 정체마진을 커버하면 None (합산이면 오발동)
#    유효259, 1차176km → need=max(176*1.15, 176+8)=202.4km, 90%usable=(90-10)*259/100=207.2 → 충분
assert origin_precharge_advice(90.0, 259.0, 176.0) is None, "먼 1차 오탐(합산 회귀)"

print(f"  출발선충전 권장(겨울 40%/1차65km/유효160) = {req}%")
print("OK — 모든 불변식 통과")
print(f"  base(@60,20°,고속) = {base:.1f} Wh/km")
print(f"  겨울-15° 고속100 = {hw:.1f},  일반60 = {lo:.1f},  비율 = {hw/lo:.3f}")

# --- 사용자 순항속도 · 도로 등급별 제한속도 ---------------------------------
from app.services.charging import (  # noqa: E402
    SPEED_LIMITS, apply_cruise_speed, highway_avg_speed,
    effective_range_from_segments as ERS,
)
from app.services.kakao import _road_class  # noqa: E402

_SEGS = [(50.0, 105.0, "highway"), (30.0, 35.0, "highway"),
         (20.0, 88.0, "expressway"), (30.0, 45.0, "local")]

# 미입력이면 기존 동작과 완전히 동일 (회귀 방지)
assert apply_cruise_speed(_SEGS, None) == _SEGS
assert apply_cruise_speed(_SEGS, 0) == _SEGS

# 희망속도는 법정 범위로 clamp된다
lo_h, hi_h = SPEED_LIMITS["highway"]
assert [v for _, v, _ in apply_cruise_speed(_SEGS, 999)][0] == min(hi_h, 105.0)
assert [v for _, v, _ in apply_cruise_speed(_SEGS, 5)][0] == lo_h  # 최저 미만 → 최저

# **정체를 덮어쓰지 않는다** — 이게 깨지면 소비 과소평가 → 방전 위험
assert apply_cruise_speed(_SEGS, 110)[1][1] == 35.0, "정체 구간이 희망속도로 덮였다"
assert apply_cruise_speed(_SEGS, 20)[1][1] == 35.0, "정체 구간보다 낮게 내려갔다"

# 일반도로에는 적용하지 않는다 (제한속도 편차가 커 교통속도가 더 낫다)
assert apply_cruise_speed(_SEGS, 110)[3] == _SEGS[3]

# 자동차전용은 고속도로보다 낮은 상한
assert SPEED_LIMITS["expressway"][1] < SPEED_LIMITS["highway"][1]
assert apply_cruise_speed([(10.0, 120.0, "expressway")], 120)[0][1] == SPEED_LIMITS["expressway"][1]

# 순항속도를 낮추면 유효거리가 늘어난다(공기저항 ∝ v²)
e_fast = ERS(300.0, 49.92, 20.0, apply_cruise_speed(_SEGS, 110))[0]
e_slow = ERS(300.0, 49.92, 20.0, apply_cruise_speed(_SEGS, 80))[0]
assert e_slow > e_fast, (e_slow, e_fast)

# 산출근거용 평균속도 = 고속·자동차전용만의 거리가중 평균(일반도로 제외)
hw = highway_avg_speed(_SEGS)
assert abs(hw - (50 * 105 + 30 * 35 + 20 * 88) / 100.0) < 0.05, hw
assert highway_avg_speed([(10.0, 40.0, "local")]) is None

# 도로 등급 판정 — 이름 우선, 이름이 없으면 속도로 근사(고속도로로 단정하지 않는다)
assert _road_class("영동고속도로", 100) == "highway"
assert _road_class("올림픽대로", 90) == "expressway"
assert _road_class("자동차전용도로", 50) == "expressway"
assert _road_class("세종대로", 40) == "local"
assert _road_class(None, 90) == "expressway"
assert _road_class(None, 40) == "local"

print("OK — 순항속도: 법정범위 clamp · 정체 비덮어쓰기 · 일반도로 미적용 · 등급별 상한")
print(f"  고속평균 {hw:.1f}km/h,  110km/h {e_fast:.0f}km → 80km/h {e_slow:.0f}km")
