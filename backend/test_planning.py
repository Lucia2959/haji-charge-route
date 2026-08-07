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

# 5) 대체 충전소는 원본보다 크게 낮은 출력을 고르지 않는다.
#    DP가 배정 충전소의 max_power_kw로 충전시간을 계산하므로, 100kW 급속 계획에
#    7kW 완속을 대체로 물리면 화면의 "28분"이 거짓이 된다(실제 3시간+).
import asyncio as _aio

from app.routers import route as _route
from app.services import ev_stations as _ev


async def _fake_avail(station_id):  # 공공 API를 타지 않고 선정 로직만 검증한다
    if station_id == "ORIG":  # 원본만 사용불가 → 대체 탐색이 돌게 한다
        return False, "점검중"
    return True, "사용가능"


_ev.station_availability = _fake_avail
_orig_loc = LatLng(lat=37.80, lng=127.51)
_cands = [
    # 같은 부지·같은 이름의 다른 사업자(공공 API가 statId를 따로 준다) — 완속뿐이다
    StationSummary(id="SLOW", name="가평(서울)휴게소", business_name="A사",
                   location=LatLng(lat=37.8005, lng=127.51),
                   charger_types=["완속"], max_power_kw=7.0),
    # 2km 밖 급속 — 더 멀어도 이쪽이 선택돼야 한다
    StationSummary(id="FAST", name="설악휴게소", business_name="B사",
                   location=LatLng(lat=37.818, lng=127.51),
                   charger_types=["급속"], max_power_kw=100.0),
]
_alt = _aio.run(_route._find_alternative(_orig_loc, _cands, {"ORIG"}, min_power_kw=50.0))
assert _alt and _alt.station_id == "FAST", f"완속을 대체로 골랐다: {_alt and _alt.station_id}"
assert _alt.business_name == "B사", "동명 충전소 구분용 사업자명이 비었다"
assert _alt.distance_km > 0, "대체소 거리가 비었다"
# 하한을 넘는 후보가 없으면 '대체 없음' — 완속을 급속인 척 안내하지 않는다
assert _aio.run(
    _route._find_alternative(_orig_loc, _cands[:1], {"ORIG"}, min_power_kw=50.0)
) is None, "출력 하한 미달인데 대체를 만들었다"

# 6) 대체소 충전시간은 대체소 출력으로 다시 계산한다.
#    100kW 계획을 50kW 대체소에 그대로 쓰면 실제보다 짧게 안내된다.
from app.models import ChargePoint as _CP
from app.services.charging import DOLPHIN_STANDARD as _VEH, _charge_minutes

_cp = _CP(order=1, distance_from_origin_km=72.1, station_id="ORIG",
          station_name="가평(서울)휴게소", location=_orig_loc,
          charge_from_pct=20.0, charge_to_pct=70.0, charge_min=28.0)
_half = StationSummary(id="HALF", name="가평(서울)휴게소", business_name="C사",
                       location=LatLng(lat=37.8005, lng=127.51),
                       charger_types=["급속"], max_power_kw=50.0)
_aio.run(_route._enrich_availability([_cp], [
    StationSummary(id="ORIG", name="가평(서울)휴게소", location=_orig_loc,
                   charger_types=["급속"], max_power_kw=100.0),
    _half,
]))
assert _cp.alternative and _cp.alternative.station_id == "HALF"
_want = round(_charge_minutes(20.0, 70.0, 50.0, _VEH.capacity_kwh))
assert _cp.alternative.charge_min == _want, (
    f"대체소 충전시간 {_cp.alternative.charge_min} != 50kW 재계산 {_want}"
)
assert _cp.alternative.charge_min > _cp.charge_min, "출력이 낮은데 시간이 안 늘었다"

print("OK — 절대거리 안전마진(겨울 상향) + 접근성 분류(방문객 우선·차종/집단 차단)")
print(f"     + 직행 선충전 권장: 5%/8.5km → {req_d}% 권장")
print(f"     + 목적지 최소잔량: 도착 SoC {dest_arr:.1f}% ≥ {_DEST_MIN_SOC}%")
print(f"     + 대체 충전소 출력 하한: 완속 배제 → {_alt.station_name} {_alt.max_power_kw}kW")
print(f"     + 대체소 충전시간 재계산: 100kW {_cp.charge_min:.0f}분 → "
      f"50kW {_cp.alternative.charge_min:.0f}분")
