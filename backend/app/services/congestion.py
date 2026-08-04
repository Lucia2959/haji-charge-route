"""충전소 혼잡도 집계·예측 (docs/07-확장설계안-성수기혼잡.md §6 F2).

큐잉 모형(M/M/c 등)을 쓰지 않는다. 충전 세션 길이는 지수분포와 거리가 멀고
(급속 80% 충전은 상당히 결정론적) 우리에겐 세션 로그가 그대로 있으므로,
**경험분포**를 쓰는 쪽이 가정도 적고 정확하다.

대기시간 추정식:

    기대 대기(분) = p_full × (svc_min_med / 2)
                     └ 측정      └ 측정

  · p_full      = 그 시간대에 전 충전기가 사용중이던 시간 비율
  · svc_min_med = 그 시간대 세션 길이의 중앙값 → 나누기 2 = 평균 잔여 서비스시간 근사
                  (만차 상태로 도착하면 진행 중 세션이 평균적으로 절반쯤 남아 있다)

두 입력 모두 관측값이다. 다만 **대기시간 자체는 관측할 수 없다** — 공공 API에
대기열 정보가 없어서, 줄 서 있는 차는 어떤 필드에도 나타나지 않는다.
그래서 이건 검증 가능한 두 값에서 유도한 파생 추정치이고, 화면에도 단일 숫자가
아니라 구간으로 표기한다. docs/07 §9-1.

ML 프레임워크는 도입하지 않는다. 통계로 부족함이 '측정'되면 그때 논의한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .. import db

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

DAYTYPE_WEEKDAY = 0
DAYTYPE_WEEKEND = 1
DAYTYPE_HOLIDAY = 2

# 콜드스타트 임계값 — 이 셀을 관측한 서로 다른 날 수.
# 5분 폴링이라 관측 밀도는 충분하고, 부족한 건 '날 수'다.
#   평일(주 5일) → 약 2주,  주말(주 2일) → 약 4주,  연휴 → 수개월~불가
# 미만이면 예측하지 않고 '데이터 부족'을 명시한다. 추측값을 내지 않는다.
MIN_DAYS = 8

# 세션 보관 기간.
#
# 실측(2026-08-04)으로 정했다. 대상 500곳 × 충전기 4대 × 세션 9.4건/일 ×
# 141 B/행 = 약 2.7 MB/일이다.
#
#   90일  → 239 MB   ✅ 무료 500MB 대비 2배 여유
#   180일 → 477 MB   (여유 없음)
#   365일 → 967 MB   ❌
#
# 90일이면 집계 창(8주=56일)과 백테스트(10주=70일)를 모두 덮는다.
# **연휴 통계는 이 기간으로 쌓이지 않는다** — 설계상 연휴는 통계가 찰 때까지
# 주말 통계로 폴백하므로 기능은 성립한다(§7 콜드스타트).
# 늘리려면 collector._MIN_POWER_KW를 함께 올려 대상을 줄여야 한다.
RETENTION_DAYS = 90

# 집계에 쓰는 관측 창(주). 계절성보다 최근 경향을 따르게 8주로 둔다.
AGGREGATE_WEEKS = 8

# 점유 표본 간격(분). 1분 단위로 재구성하면 조인 결과가 10배가 되는데,
# 혼잡 판정에 그만한 해상도가 필요 없다.
SAMPLE_MIN = 10

# 한국 공휴일 — 연휴 판정용.
#
# ⚠ **음력 기반 공휴일(설날·추석·부처님오신날)은 배포 전 공식 달력으로 반드시
#    확인할 것.** 아래 값은 계산으로 유도한 것이라 하루 이틀 어긋날 수 있다.
#    매년 1회 갱신이 필요하다(공공 특일정보 API를 하나 더 붙이는 것보다 싸다).
#
# 다만 지금 당장의 영향은 거의 없다 — 연휴 셀이 MIN_DAYS(8일)에 닿기까지는
# 수개월이 걸리고, 그 전까지는 주말 통계로 폴백하기 때문이다.
_HOLIDAYS: set[date] = {
    # 2026 — 양력 고정
    date(2026, 1, 1), date(2026, 3, 1), date(2026, 3, 2),   # 삼일절 대체
    date(2026, 5, 5), date(2026, 6, 6), date(2026, 8, 15),
    date(2026, 10, 3), date(2026, 10, 9), date(2026, 12, 25),
    # 2026 — 음력(⚠ 확인 필요)
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),   # 설 연휴
    date(2026, 5, 24),                                          # 부처님오신날
    date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26),   # 추석 연휴
    # 2027 — 양력 고정
    date(2027, 1, 1), date(2027, 3, 1), date(2027, 5, 5),
    date(2027, 6, 6), date(2027, 8, 15), date(2027, 10, 3),
    date(2027, 10, 9), date(2027, 12, 25),
}


def daytype_of(dt: datetime) -> int:
    """시각 → 요일유형. 공휴일이 주말보다 우선한다(연휴 수요가 훨씬 크다)."""
    d = dt.astimezone(KST).date()
    if d in _HOLIDAYS:
        return DAYTYPE_HOLIDAY
    return DAYTYPE_WEEKEND if d.weekday() >= 5 else DAYTYPE_WEEKDAY


@dataclass(frozen=True)
class Prediction:
    """충전소 혼잡 예측 1건. status가 'ok'가 아니면 나머지는 참고하지 않는다."""

    status: str          # "ok" | "insufficient_data" | "unavailable"
    n_days: int = 0
    level: str = ""      # "여유" | "보통" | "혼잡"
    wait_min: float = 0.0        # 기대 대기(분) — DP가 쓰는 값
    wait_lo: int = 0             # 화면 표기용 구간
    wait_hi: int = 0
    confidence: str = ""         # "낮음" | "보통" | "높음"
    daytype_fallback: str = ""   # 연휴 통계가 없어 주말로 대체했을 때 "weekend"


_UNAVAILABLE = Prediction(status="unavailable")
_INSUFFICIENT_TMPL = "insufficient_data"


def predict_wait(row: dict | None, daytype_fallback: str = "") -> Prediction:
    """집계 1행 → 예측. 순수 함수(DB·네트워크 없음).

    row가 없거나 관측일이 MIN_DAYS 미만이면 예측하지 않는다.
    """
    if row is None:
        return Prediction(status=_INSUFFICIENT_TMPL, n_days=0)
    n_days = int(row["n_days"])
    if n_days < MIN_DAYS:
        return Prediction(status=_INSUFFICIENT_TMPL, n_days=n_days)

    occ = float(row["occ_mean"])
    p_full = float(row["p_full"])
    svc = float(row["svc_min_med"])

    # 만차로 도착할 확률 × 평균 잔여 서비스시간
    expected = p_full * (svc / 2.0)

    if occ >= 0.8 or p_full >= 0.3:
        level = "혼잡"
    elif occ >= 0.5:
        level = "보통"
    else:
        level = "여유"

    # 관측일이 많을수록 신뢰도가 높다. 연휴를 주말로 대체한 경우는 한 단계 낮춘다.
    if n_days >= 24:
        conf = "높음"
    elif n_days >= 14:
        conf = "보통"
    else:
        conf = "낮음"
    if daytype_fallback:
        conf = "낮음" if conf != "높음" else "보통"

    return Prediction(
        status="ok",
        n_days=n_days,
        level=level,
        wait_min=round(expected, 1),
        wait_lo=_round5(expected * 0.7),
        wait_hi=_round5(expected * 1.5),
        confidence=conf,
        daytype_fallback=daytype_fallback,
    )


def _round5(x: float) -> int:
    """5분 단위 반올림. 분 단위로 찍으면 있지도 않은 정밀도를 주장하게 된다."""
    return int(round(x / 5.0) * 5)


async def load_stats(
    station_ids: list[str], daytype: int, hours: list[int]
) -> dict[tuple[str, int], Prediction]:
    """(충전소, 도착 시간대)별 예측을 **한 번의 쿼리로** 가져온다.

    계획 API가 충전소마다 조회하면 왕복이 쌓이므로 배치 1쿼리로 끝낸다.
    외부 네트워크를 타지 않아(로컬 DB 집계) 응답시간 예산에 거의 영향이 없다.

    시간대를 리스트로 받는 이유: 장거리 경로는 충전소마다 도착 시각이 달라
    같은 요청 안에서도 여러 시간대가 필요하다(4시간 주행이면 5개 시간대).

    연휴인데 연휴 통계가 부족하면 주말 통계로 폴백한다. 주말을 연휴에 쓰면
    과소추정이므로 daytype_fallback을 채워 화면에서 함께 고지하게 한다.

    요일유형은 **출발 시각 기준 하나**로 고정한다. 자정을 넘기는 경로에서는
    실제와 어긋날 수 있으나, 성수기 당일치기 이동이 대상이라 실익이 없다.
    """
    if not station_ids or not hours:
        return {}
    p = db.pool()
    if p is None:
        return {(sid, h): _UNAVAILABLE for sid in station_ids for h in hours}

    try:
        async with p.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT station_id, daytype, hour, n_days, occ_mean, p_full, svc_min_med
                  FROM occupancy_stat
                 WHERE station_id = ANY($1::text[])
                   AND hour       = ANY($2::smallint[])
                   AND daytype    = ANY($3::smallint[])
                """,
                station_ids,
                hours,
                # 연휴면 주말 통계도 함께 가져와 폴백 후보로 쓴다
                [daytype, DAYTYPE_WEEKEND] if daytype == DAYTYPE_HOLIDAY else [daytype],
            )
    except Exception as exc:  # noqa: BLE001 — 예측 실패로 계획이 죽으면 안 된다
        log.warning("혼잡 통계 조회 실패 — 예측 없이 진행: %s", exc)
        return {(sid, h): _UNAVAILABLE for sid in station_ids for h in hours}

    primary = {
        (r["station_id"], r["hour"]): dict(r) for r in rows if r["daytype"] == daytype
    }
    weekend = {
        (r["station_id"], r["hour"]): dict(r)
        for r in rows
        if r["daytype"] == DAYTYPE_WEEKEND
    }

    out: dict[tuple[str, int], Prediction] = {}
    for sid in station_ids:
        for h in hours:
            row = primary.get((sid, h))
            fallback = ""
            if (row is None or row["n_days"] < MIN_DAYS) and daytype == DAYTYPE_HOLIDAY:
                alt = weekend.get((sid, h))
                if alt is not None and alt["n_days"] >= MIN_DAYS:
                    row, fallback = alt, "weekend"
            out[(sid, h)] = predict_wait(row, fallback)
    return out


@dataclass
class WaitLookup:
    """DP에 주입할 대기시간 조회기.

    한 번의 배치 쿼리 결과를 들고 있다가 클로저로 응답한다 — **DP 실행 중에는
    DB를 치지 않는다.** 그래야 계획 응답시간 예산(웜 5초)을 지킬 수 있다.
    """

    depart_at: datetime
    preds: dict[tuple[str, int], Prediction]

    def at(self, station_id: str, elapsed_min: float) -> Prediction | None:
        """출발 후 elapsed_min에 그 충전소에 도착했을 때의 예측."""
        arrive = self.depart_at + timedelta(minutes=elapsed_min)
        return self.preds.get((station_id, arrive.hour))

    def wait_min(self, station_id: str, elapsed_min: float) -> float:
        """DP가 정지 오버헤드에 더할 분(分). 데이터 부족이면 0 → 기존 고정값 폴백."""
        p = self.at(station_id, elapsed_min)
        return p.wait_min if p is not None and p.status == "ok" else 0.0


async def wait_lookup(
    station_ids: list[str], depart_at: datetime, span_min: float
) -> WaitLookup:
    """출발 시각과 주행 소요시간으로 필요한 시간대만 골라 예측을 미리 받아둔다."""
    base = depart_at.astimezone(KST)
    # 주행 중 지나는 시간대 + 충전 정차분 여유 1시간
    n = min(24, int(span_min // 60) + 3)
    hours = sorted({(base + timedelta(hours=i)).hour for i in range(n)})
    preds = await load_stats(station_ids, daytype_of(base), hours)
    return WaitLookup(depart_at=base, preds=preds)


# 세션 구간에서 점유 시계열을 역산해 (충전소 × 요일유형 × 시간대)로 집계한다.
#
# 충전기 대수는 session에서 본 서로 다른 charger_id 수로 잡는다. 한 번도 안 쓰인
# 충전기는 빠지므로 대수를 과소평가할 수 있고, 그러면 점유율이 실제보다 높게 나온다.
# 이 편향은 '더 붐빈다'는 쪽이라 방전 위험을 다루는 앱에서는 안전한 방향이다.
#
# grid는 충전소별 첫 관측 이후만 만든다. 그러지 않으면 나중에 추가된 충전소의
# 과거 구간이 전부 '한산했음'으로 잘못 집계된다.
_AGGREGATE_SQL = f"""
WITH win AS (
  SELECT now() - interval '{AGGREGATE_WEEKS} weeks' AS from_ts
),
sta AS (
  -- 점유 재구성 구간은 **실제로 관측을 시작한 뒤**로만 잡는다.
  -- 첫 수집의 백필(직전 세션 1건)이 일주일 전 것이면 MIN(started_at)은 일주일 전이
  -- 되는데, 그 사이를 관측한 게 아니라서 전부 '한산'으로 잘못 집계된다.
  -- station_seen.first_seen_at이 그 경계다.
  SELECT s.station_id,
         COUNT(DISTINCT s.charger_id)::int AS n_ch,
         GREATEST(MIN(s.started_at), w.from_ts, ss.first_seen_at) AS first_ts
    FROM session s
    CROSS JOIN win w
    JOIN station_seen ss ON ss.station_id = s.station_id
   WHERE s.started_at >= w.from_ts
   GROUP BY s.station_id, w.from_ts, ss.first_seen_at
),
grid AS (
  SELECT sta.station_id, sta.n_ch, g.ts
    FROM sta
    CROSS JOIN LATERAL generate_series(
      date_trunc('hour', sta.first_ts), now(), interval '{SAMPLE_MIN} minutes'
    ) AS g(ts)
),
occ AS (
  SELECT g.station_id,
         g.n_ch,
         g.ts,
         COUNT(x.charger_id) AS busy
    FROM grid g
    LEFT JOIN session x
      ON x.station_id = g.station_id
     AND x.started_at <= g.ts
     AND x.ended_at   >  g.ts
   GROUP BY g.station_id, g.n_ch, g.ts
),
cell AS (
  SELECT station_id,
         n_ch,
         (CASE
            WHEN (ts AT TIME ZONE 'Asia/Seoul')::date = ANY($1::date[]) THEN 2
            WHEN EXTRACT(ISODOW FROM ts AT TIME ZONE 'Asia/Seoul') >= 6  THEN 1
            ELSE 0
          END)::smallint                                          AS daytype,
         EXTRACT(HOUR FROM ts AT TIME ZONE 'Asia/Seoul')::smallint AS hour,
         (ts AT TIME ZONE 'Asia/Seoul')::date                      AS day,
         busy
    FROM occ
),
svc AS (
  SELECT x.station_id,
         (CASE
            WHEN (x.started_at AT TIME ZONE 'Asia/Seoul')::date = ANY($1::date[]) THEN 2
            WHEN EXTRACT(ISODOW FROM x.started_at AT TIME ZONE 'Asia/Seoul') >= 6  THEN 1
            ELSE 0
          END)::smallint                                                    AS daytype,
         EXTRACT(HOUR FROM x.started_at AT TIME ZONE 'Asia/Seoul')::smallint AS hour,
         PERCENTILE_CONT(0.5) WITHIN GROUP (
           ORDER BY EXTRACT(EPOCH FROM (x.ended_at - x.started_at)) / 60.0
         ) AS med
    FROM session x CROSS JOIN win w
   WHERE x.started_at >= w.from_ts
   GROUP BY 1, 2, 3
)
INSERT INTO occupancy_stat
  (station_id, daytype, hour, n_days, occ_mean, p_full, svc_min_med, updated_at)
SELECT c.station_id,
       c.daytype,
       c.hour,
       COUNT(DISTINCT c.day)::smallint,
       (AVG(c.busy::real / GREATEST(c.n_ch, 1)))::real,
       (AVG(CASE WHEN c.busy >= c.n_ch THEN 1.0 ELSE 0.0 END))::real,
       COALESCE(MAX(s.med), 0)::real,
       now()
  FROM cell c
  LEFT JOIN svc s
    ON s.station_id = c.station_id AND s.daytype = c.daytype AND s.hour = c.hour
 GROUP BY c.station_id, c.daytype, c.hour
ON CONFLICT (station_id, daytype, hour) DO UPDATE SET
  n_days      = EXCLUDED.n_days,
  occ_mean    = EXCLUDED.occ_mean,
  p_full      = EXCLUDED.p_full,
  svc_min_med = EXCLUDED.svc_min_med,
  updated_at  = EXCLUDED.updated_at
"""


async def aggregate() -> dict:
    """세션 → occupancy_stat 재집계 + 보관기간 초과 세션 삭제.

    하루 1회 실행한다(크론). 계획 API는 이 결과만 읽으므로, 집계가 몇 십 초
    걸려도 사용자 응답시간에는 영향이 없다.
    """
    p = db.pool()
    if p is None:
        return {"ok": False, "reason": "db_unavailable"}

    holidays = sorted(_HOLIDAYS)
    async with p.acquire() as conn:
        # 전량 재계산이므로 기존 집계를 먼저 비운다. ON CONFLICT UPDATE만 쓰면
        # 이번에 안 나온 셀(대상에서 빠진 충전소, 좁아진 관측 구간)이 옛 값 그대로
        # 남아 계속 예측에 쓰인다. 트랜잭션으로 묶어 조회가 빈 표를 보지 않게 한다.
        async with conn.transaction():
            await conn.execute("DELETE FROM occupancy_stat")
            await conn.execute(_AGGREGATE_SQL, holidays)
        cells = await conn.fetchval("SELECT COUNT(*) FROM occupancy_stat")
        ready = await conn.fetchval(
            "SELECT COUNT(*) FROM occupancy_stat WHERE n_days >= $1", MIN_DAYS
        )
        pruned = await conn.execute(
            f"DELETE FROM session WHERE started_at < now() - interval '{RETENTION_DAYS} days'"
        )
        sessions = await conn.fetchval("SELECT COUNT(*) FROM session")

    return {
        "ok": True,
        "cells": cells,
        "cells_ready": ready,      # MIN_DAYS를 넘겨 실제 예측에 쓰이는 셀 수
        "sessions": sessions,
        "pruned": pruned,
    }
