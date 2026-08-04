"""성수기 충전 혼잡 예측 자체검증 (docs/07).
실행: python test_congestion.py

DB 없이 도는 순수 로직만 검증한다 — 집계 SQL은 실제 Postgres가 있어야 하므로
여기서 다루지 않는다(/internal/aggregate 응답의 cells_ready로 확인).
"""
from datetime import datetime, timedelta

from app.models import LatLng, StationSummary
from app.services.charging import _STOP_OVERHEAD_MIN, cumulative_distances, plan_charging_dp
from app.services.collector import _parse_kst, _districts
from app.services.congestion import (
    DAYTYPE_HOLIDAY, DAYTYPE_WEEKDAY, DAYTYPE_WEEKEND, KST, MIN_DAYS,
    WaitLookup, daytype_of, predict_wait,
)
from app.services.ev_stations import normalize_zscode


def cell(n_days, occ=0.9, p_full=0.5, svc=40.0):
    return {"n_days": n_days, "occ_mean": occ, "p_full": p_full, "svc_min_med": svc}


# 1) 콜드스타트 — 관측일이 임계 미만이면 '추측값'을 내지 않는다 (완료기준 2)
assert predict_wait(None).status == "insufficient_data"
assert predict_wait(cell(MIN_DAYS - 1)).status == "insufficient_data"
assert predict_wait(cell(MIN_DAYS)).status == "ok"
#    부족 판정일 때는 대기시간이 0이어야 한다 → DP가 기존 고정 오버헤드로 폴백
assert predict_wait(cell(MIN_DAYS - 1)).wait_min == 0.0

# 2) 대기시간 추정식 = p_full × (svc_min_med / 2). 두 입력 모두 측정값이다.
p = predict_wait(cell(30, p_full=0.5, svc=40.0))
assert abs(p.wait_min - 10.0) < 1e-6, p.wait_min
assert p.wait_lo <= p.wait_min <= p.wait_hi, (p.wait_lo, p.wait_hi)
#    표기 구간은 5분 단위 — 있지도 않은 정밀도를 주장하지 않는다
assert p.wait_lo % 5 == 0 and p.wait_hi % 5 == 0
#    만차가 없으면 대기도 없다
assert predict_wait(cell(30, p_full=0.0)).wait_min == 0.0

# 3) 혼잡 등급 경계
assert predict_wait(cell(30, occ=0.85, p_full=0.1)).level == "혼잡"   # 점유율 기준
assert predict_wait(cell(30, occ=0.3, p_full=0.35)).level == "혼잡"   # 만차빈도 기준
assert predict_wait(cell(30, occ=0.6, p_full=0.1)).level == "보통"
assert predict_wait(cell(30, occ=0.2, p_full=0.05)).level == "여유"

# 4) 신뢰도 — 관측일이 적을수록 낮고, 연휴를 주말로 대체하면 한 단계 내린다
assert predict_wait(cell(30)).confidence == "높음"
assert predict_wait(cell(10)).confidence == "낮음"
assert predict_wait(cell(30), "weekend").confidence == "보통"
assert predict_wait(cell(30), "weekend").daytype_fallback == "weekend"

# 5) 요일유형 — 공휴일이 주말보다 우선한다
assert daytype_of(datetime(2026, 8, 5, 10, tzinfo=KST)) == DAYTYPE_WEEKDAY   # 수
assert daytype_of(datetime(2026, 8, 8, 10, tzinfo=KST)) == DAYTYPE_WEEKEND   # 토
assert daytype_of(datetime(2026, 8, 15, 10, tzinfo=KST)) == DAYTYPE_HOLIDAY  # 광복절(토)
assert daytype_of(datetime(2026, 1, 1, 10, tzinfo=KST)) == DAYTYPE_HOLIDAY   # 신정(목)

# 6) WaitLookup — 도착 시각의 '시간대'로 예측을 고른다
base = datetime(2026, 9, 25, 8, 0, tzinfo=KST)  # 추석 연휴 오전 8시
wl = WaitLookup(
    depart_at=base,
    preds={
        ("A", 8): predict_wait(cell(30, p_full=0.0)),   # 출발 직후엔 한산
        ("A", 11): predict_wait(cell(30, p_full=0.8, svc=40.0)),  # 3시간 뒤엔 만차
    },
)
assert wl.wait_min("A", 0) == 0.0
assert abs(wl.wait_min("A", 180) - 16.0) < 1e-6, wl.wait_min("A", 180)
assert wl.wait_min("A", 60) == 0.0      # 9시 통계 없음 → 폴백
assert wl.wait_min("없는충전소", 0) == 0.0

# 7) 성수기 시나리오 회귀 (완료기준 3)
#    연휴 오전 서울→강원. 혼잡 예측이 붙으면 총 시간이 늘고, 붐비는 곳을 피해 간다.
def line(total_km, step=2.0):
    n = int(total_km / step)
    dlat = (total_km / 111.0) / n
    return [LatLng(lat=37.5 + i * dlat, lng=128.0) for i in range(n + 1)]


def _first_leg_km(station, path, cum):
    """출발지에서 그 충전소까지의 경로 거리(근사) — 도달 가능성 판정용."""
    idx = min(
        range(len(path)),
        key=lambda j: abs(path[j].lat - station.location.lat),
    )
    return cum[idx]


path = line(230)
cum = cumulative_distances(path)
stations, km, i = [], 60.0, 0
while km < cum[-1] - 20:
    idx = min(range(len(cum)), key=lambda j: abs(cum[j] - km))
    stations.append(
        StationSummary(
            id=f"S{i}", name=f"휴게소{i}",
            location=LatLng(lat=path[idx].lat, lng=path[idx].lng + 0.01),
            charger_types=["급속"], max_power_kw=100.0,
        )
    )
    km += 35.0
    i += 1

#    출발 SoC는 '첫 충전소가 여러 곳 도달 가능'하도록 잡는다. 낮게 잡으면 후보가
#    하나뿐이라 회피가 원천적으로 불가능해져, 코드가 아니라 시나리오를 검증하게 된다.
eff, spd, start_soc = 200.0, 90.0, 80.0
base_pts, _, base_ok, base_min = plan_charging_dp(path, start_soc, eff, spd, stations)
assert base_ok and base_pts, "기준 계획 실패"
reach_km = (start_soc - 25.0 / eff * 100.0) * (eff / 100.0)
assert sum(1 for s in stations if _first_leg_km(s, path, cum) <= reach_km) >= 2, (
    "첫 구간에 도달 가능한 충전소가 하나뿐이면 회피 테스트가 의미 없다"
)

#    모든 충전소가 붐빈다고 하면 총 충전·정차 시간이 그만큼 늘어야 한다
WAIT = 25.0
all_busy, _, ok, busy_min = plan_charging_dp(
    path, start_soc, eff, spd, stations, wait_min_fn=lambda sid, t: WAIT
)
assert ok, "혼잡 반영 계획 실패"
assert busy_min >= base_min + WAIT * 0.9, (base_min, busy_min)
#    대기가 정지 오버헤드에 더해졌으므로, 정지 1회 비용이 커져 충전 횟수는 늘지 않는다
assert len(all_busy) <= len(base_pts), (len(base_pts), len(all_busy))

#    특정 충전소만 붐비면 계획이 그 충전소를 피한다
busy_id = base_pts[0].station_id
avoided, _, ok, _ = plan_charging_dp(
    path, start_soc, eff, spd, stations,
    wait_min_fn=lambda sid, t: 60.0 if sid == busy_id else 0.0,
)
assert ok, "회피 계획 실패"
assert busy_id not in [c.station_id for c in avoided], "혼잡 충전소를 피하지 못함"

#    wait_min_fn이 없으면 기존 동작과 완전히 동일해야 한다(회귀 방지)
same_pts, _, _, same_min = plan_charging_dp(path, start_soc, eff, spd, stations, wait_min_fn=None)
assert same_min == base_min and len(same_pts) == len(base_pts)
#    arrive_after_min은 경로 순서대로 증가한다(대기 조회의 기준 시각)
arrivals = [c.arrive_after_min for c in base_pts]
assert all(a is not None for a in arrivals)
assert arrivals == sorted(arrivals), arrivals
assert arrivals[0] >= 0 and _STOP_OVERHEAD_MIN > 0

# 8) 일반구 zscode 정규화 — 공공 API에 없는 코드를 상위 시로 내린다
#    (실측: 41135 분당 0건 / 41130 성남 10,799건)
assert normalize_zscode("41135") == "41130"  # 성남 분당구 → 성남시
assert normalize_zscode("41465") == "41460"  # 용인 수지구 → 용인시
assert normalize_zscode("41285") == "41280"  # 고양 일산동구 → 고양시
assert normalize_zscode("41117") == "41110"  # 수원 영통구 → 수원시
#    자치구·시·군은 이미 0으로 끝나 그대로 통과
for code in ("11650", "11680", "51150", "41820", "51830"):
    assert normalize_zscode(code) == code, code
#    길이가 다르면 손대지 않는다
assert normalize_zscode("41") == "41"

# 9) 수집기 — 공공 API 시각 파싱과 기본 회랑
d = _parse_kst("20260804102257")
assert d is not None and d.year == 2026 and d.hour == 10 and d.utcoffset() == timedelta(hours=9)
assert _parse_kst("") is None and _parse_kst("2026080410225") is None
assert _parse_kst("2026139910225x") is None
#    기본 회랑은 전부 정규화된 코드여야 한다(하나라도 일반구면 0건 조회가 된다)
for z, zs in _districts():
    assert normalize_zscode(zs) == zs, (z, zs)
    assert zs.startswith(z), (z, zs)

# 10) 회귀 방지 — 자체검증 목록에 이 파일이 들어 있어야 한다.
#     변경 후 실행할 테스트가 README/TODO에서 빠지면 아무도 안 돌린다.
from pathlib import Path

_todo = (Path(__file__).resolve().parents[1] / "TODO.md").read_text(encoding="utf-8")
assert "test_congestion.py" in _todo, "TODO.md 자체검증 목록에 test_congestion.py 누락"

print("OK — 혼잡 예측: 콜드스타트 경계 / 추정식 / 등급 / 요일유형 / 시간대 조회")
print("     + 성수기 회귀: 대기 반영 시 총시간 증가·혼잡 충전소 회피·무주입 시 기존과 동일")
print(f"     + zscode 정규화(일반구→시), 회랑 {len(_districts())}개 시군구 검증")
print(f"  기준계획 {len(base_pts)}회/{base_min:.0f}분 → 전지점 혼잡 {busy_min:.0f}분")
