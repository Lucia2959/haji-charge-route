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
adv2 = origin_precharge_advice(40.0, 160.0, 65.0, first_unavailable=True)
assert adv2 and "사용불가" in adv2[1], "사용불가 사유 미반영"
#    오탐 방지(핵심): 먼 1차라도 현 충전량이 정체마진을 커버하면 None (합산이면 오발동)
#    유효259, 1차176km → need=max(176*1.15, 176+8)=202.4km, 90%usable=(90-10)*259/100=207.2 → 충분
assert origin_precharge_advice(90.0, 259.0, 176.0) is None, "먼 1차 오탐(합산 회귀)"

print(f"  출발선충전 권장(겨울 40%/1차65km/유효160) = {req}%")
print("OK — 모든 불변식 통과")
print(f"  base(@60,20°,고속) = {base:.1f} Wh/km")
print(f"  겨울-15° 고속100 = {hw:.1f},  일반60 = {lo:.1f},  비율 = {hw/lo:.3f}")
