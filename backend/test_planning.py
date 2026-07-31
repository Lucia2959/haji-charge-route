"""주행안정성(절대거리 안전마진) + 충전소 접근성 분류 자체검증.
실행: python test_planning.py
"""
import math as _m

from app.models import LatLng, StationSummary
from app.services.charging import (
    _DEST_MIN_SOC, _MIN_BUFFER_KM, _effective_reserve_pct,
    cumulative_distances, origin_precharge_advice, plan_charging_dp,
)
from app.services.ev_stations import _access_class

# 1) 절대거리 안전마진 하한
#    여름(유효거리 큼): 25/330 = 7.6% < 10 → 기본 10% 유지
assert _effective_reserve_pct(10.0, 330.0) == 10.0
#    겨울(유효거리 작음): 10%면 실제 16km라 위험 → 25km의 %로 상향
r_w = _effective_reserve_pct(10.0, 160.0)
assert abs(r_w - _MIN_BUFFER_KM / 160.0 * 100.0) < 1e-9
assert r_w > 15.0, f"겨울 reserve 상향 실패: {r_w}"
#    상향된 reserve의 실제 거리 = _MIN_BUFFER_KM 보장
assert abs(r_w / 100.0 * 160.0 - _MIN_BUFFER_KM) < 1e-6

# 2) 접근성 분류 — 외부인 출입허용 vs 비인가자/차종 전용
USABLE = "open", "open_fee"
assert _access_class("N", "") == "open"
# 외부인 이용가능(상가/호텔/사무실/고객/방문객)
for d in ("고객 전용", "이용객 전용", "호텔 투숙객 전용", "상가 이용고객", "유료주차 후 이용"):
    assert _access_class("Y", d) in USABLE, d
# 방문객 우선(입주/관계자 키워드와 겹쳐도 사용가능)
assert _access_class("Y", "오피스 입주사 방문객") in USABLE
assert _access_class("Y", "입주민 방문객 주차 후 이용") in USABLE
# 비인가자 전용(불가)
assert _access_class("Y", "입주민 전용") == "residents"
assert _access_class("Y", "아파트 입주자용") == "residents"
assert _access_class("Y", "임직원 전용") == "staff"
assert _access_class("Y", "관계자 외 출입금지") == "staff"
# 특정 차종/집단 전용(불가) — 승용 EV 사용 불가
for d in ("전기버스 전용", "화물차 전용", "택시 전용", "카셰어링 전용", "쏘카 전용",
          "관용차량 전용", "소방서 전용"):
    assert _access_class("Y", d) == "fleet", d

# 3) 목적지 도착 시 최소 _DEST_MIN_SOC(15%) 잔량 — 목적지 충전소 유무와 무관
def _line(total, step=2.0):
    n = int(total / step); dlat = (total / 111.0) / n
    return [LatLng(lat=35.0 + i*dlat, lng=127.5) for i in range(n + 1)]

path = _line(200)
cum = cumulative_distances(path); total = cum[-1]
sts, k, i = [], 40.0, 0
while k < total - 10:
    idx = min(range(len(cum)), key=lambda j: abs(cum[j] - k))
    sts.append(StationSummary(id=f"S{i}", name=f"충전{i}",
        location=LatLng(lat=path[idx].lat, lng=path[idx].lng + 0.01),
        charger_types=["급속"], max_power_kw=100.0))
    k += 60.0; i += 1
eff = 250.0
cps, usable, feas, _ = plan_charging_dp(path, 40.0, eff, 80.0, sts)
assert feas and cps, "계획 실패"
kmp = eff / 100.0; soc, pos = 40.0, 0.0
for cp in cps:
    soc, pos = cp.charge_to_pct, cp.distance_from_origin_km
dest_arr = soc - (total - pos) / kmp
assert dest_arr >= _DEST_MIN_SOC - 1.0, f"목적지 도착 {dest_arr:.1f}% < {_DEST_MIN_SOC}%"

# 4) 충전 없이 목적지 직행이지만 도착 잔량이 15% 미만이면 선충전 권장이 나와야 한다
#    (짧은 구간이라 charge_points가 비어도 권장이 누락되면 안 됨 — 실제 누락 버그였음)
adv_dest = origin_precharge_advice(5.0, 296.0, 8.5, is_destination=True)
assert adv_dest is not None, "직행인데 도착 2%면 선충전 권장이 나와야 함"
req_d, reason_d = adv_dest
want_d = _m.ceil(_DEST_MIN_SOC + 8.5 * 1.15 / 296.0 * 100)
assert req_d == want_d, f"직행 권장값 {req_d} != 공식 {want_d}"
assert "15%" in reason_d and "목적지" in reason_d
# 충전량이 충분하면(예: 50%) 권장하지 않는다
assert origin_precharge_advice(50.0, 296.0, 8.5, is_destination=True) is None
# 목적지 기준은 중간 충전소 기준보다 하한이 높다(15% vs reserve 10%)
mid = origin_precharge_advice(5.0, 296.0, 8.5)
assert mid and req_d > mid[0], "목적지 직행 하한(15%)이 중간 충전소보다 높아야 함"

print("OK — 절대거리 안전마진(겨울 상향) + 접근성 분류(방문객 우선·차종/집단 차단)")
print(f"     + 직행 선충전 권장: 5%/8.5km → {req_d}% 권장")
print(f"     + 목적지 최소잔량: 도착 SoC {dest_arr:.1f}% ≥ {_DEST_MIN_SOC}%")
