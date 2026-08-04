"""충전 세션 수집기 (docs/07-확장설계안-성수기혼잡.md §6 F1).

공공 API `getChargerStatus`는 최근 10분 안에 상태가 바뀐 충전기를 반환하는데,
각 행에 **직전 완료 세션의 시작·종료 시각**(lastTsdt/lastTedt)이 들어 있다.
즉 점유율을 표본으로 찍는 게 아니라 **세션 이벤트를 그대로 적재**할 수 있다.
덕분에 '평균 충전 점유시간'을 상수로 가정하지 않고 충전소별로 측정한다.

폴링 주기는 5분이다. 피드 윈도가 10분 고정이므로 10분이 상한인데,
크론 지연이나 인스턴스 슬립 복귀로 한 번만 밀려도 그 사이 변경이 영구히 사라진다.
5분이면 2배 겹치고, 중복분은 PK(station_id, charger_id, started_at)로 무시된다.

사용자 요청 경로에는 들어가지 않는다 — cron-job.org가 /internal/collect를 호출한다.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

from .. import db
from ..config import settings
from ..http import QuotaExceeded
from . import ev_stations
from .charging import _is_highway_stop

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 회랑 기본값 — 영동·서울양양 축. 전부 실호출로 조회 가능함을 확인했다(2026-08-04).
# 성남 41130 / 용인 41460은 시 단위 코드다. 일반구 코드(41135 분당, 41465 수지)는
# 공공 API에 없어 0건이 나온다 — ev_stations.normalize_zscode() 참고.
_DEFAULT_DISTRICTS: list[tuple[str, str]] = [
    ("11", "11650"),  # 서울 서초
    ("11", "11680"),  # 서울 강남
    ("41", "41130"),  # 경기 성남
    ("41", "41360"),  # 경기 남양주
    ("41", "41450"),  # 경기 하남
    ("41", "41460"),  # 경기 용인
    ("41", "41500"),  # 경기 이천
    ("41", "41610"),  # 경기 광주
    ("41", "41670"),  # 경기 여주
    ("41", "41820"),  # 경기 가평
    ("51", "51110"),  # 강원 춘천
    ("51", "51130"),  # 강원 원주
    ("51", "51150"),  # 강원 강릉
    ("51", "51210"),  # 강원 속초
    ("51", "51720"),  # 강원 홍천
    ("51", "51730"),  # 강원 횡성
    ("51", "51760"),  # 강원 평창
    ("51", "51810"),  # 강원 인제
    ("51", "51830"),  # 강원 양양
]

# 대상 충전소 판정: 급속이면서 외부인 이용가능하고, 고속도로 휴게소이거나 고출력.
# 성수기 병목은 장거리 이동 중 들르는 고출력 급속에서 생긴다. 시내 완속까지 담으면
# 세션 수가 몇 배가 되어 무료 Postgres 500MB를 몇 달 만에 채운다.
_MIN_POWER_KW = 100.0

# 비정상 세션 배제. 완속 야간 방치·기기 오류로 12시간짜리 '세션'이 들어오면
# 점유율 통계가 통째로 망가진다.
_MAX_SESSION_MIN = 12 * 60
_MIN_SESSION_MIN = 1

# 대상 충전소 목록 캐시. 카탈로그 TTL(24h)과 맞춘다.
_TARGETS_TTL_SEC = 24 * 3600.0
_targets: set[str] = set()
_targets_at: float = 0.0

# 일일 호출 예산. 계획 API가 쓸 쿼터를 수집기가 먼저 태우지 않도록 자체 상한을 둔다.
# 공공 API의 실제 한도와는 별개다(그건 초과하면 QuotaExceeded로 온다).
_budget_day: date | None = None
_budget_used = 0


def _districts() -> list[tuple[str, str]]:
    """수집 대상 시군구. 환경변수 우선, 없으면 회랑 기본값."""
    raw = settings.collect_districts.strip()
    if not raw:
        return _DEFAULT_DISTRICTS
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        z, zs = part.split(":", 1)
        out.append((z.strip(), ev_stations.normalize_zscode(zs.strip())))
    return out or _DEFAULT_DISTRICTS


def _parse_kst(s: str) -> datetime | None:
    """공공 API 시각 문자열(yyyyMMddHHmmss, KST) → aware datetime."""
    if not s or len(s) != 14 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except ValueError:
        return None


def _budget_left() -> int:
    """오늘 남은 자체 호출 예산. KST 날짜가 바뀌면 리셋."""
    global _budget_day, _budget_used
    today = datetime.now(KST).date()
    if _budget_day != today:
        _budget_day, _budget_used = today, 0
    return settings.collect_daily_budget - _budget_used


def _spend(n: int) -> None:
    global _budget_used
    _budget_used += n


async def refresh_targets(force: bool = False) -> set[str]:
    """회랑 카탈로그에서 대상 충전소 ID 집합을 만든다(24h 캐시).

    getChargerStatus에는 위치·충전기타입·개방여부가 없어서, 어떤 statId를 저장할지
    판단하려면 카탈로그와 조인해야 한다. 카탈로그는 기존 _get_catalog(24h 캐시)를
    그대로 쓰므로 하루 시군구당 1회만 실제 호출이 나간다.
    """
    global _targets, _targets_at
    now = time.monotonic()
    if not force and _targets and now - _targets_at < _TARGETS_TTL_SEC:
        return _targets

    found: set[str] = set()
    for zcode, zscode in _districts():
        try:
            for st in await ev_stations._get_catalog(zcode, zscode):
                if not st.public_access:
                    continue  # 입주민·관계자·특정차량 전용은 계획 후보가 아니다
                if "급속" not in st.charger_types:
                    continue
                if _is_highway_stop(st.name) or st.max_power_kw >= _MIN_POWER_KW:
                    found.add(st.id)
        except QuotaExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 — 시군구 하나 실패로 전체를 멈추지 않는다
            log.warning("대상 갱신 실패 %s:%s — %s", zcode, zscode, exc)

    if found:
        _targets, _targets_at = found, now
    # 대상이 400개를 크게 넘으면 저장량 추정(21MB/월)이 무너진다.
    # 그럴 땐 COLLECT_DISTRICTS를 좁히거나 _MIN_POWER_KW를 올린다.
    log.info("수집 대상 충전소 %d개 (시군구 %d)", len(_targets), len(_districts()))
    return _targets


async def collect_once() -> dict:
    """상태 피드 1회 수집 → 대상 충전소의 완료 세션을 적재."""
    p = db.pool()
    if p is None:
        return {"ok": False, "reason": "db_unavailable"}
    if not settings.use_ev_api:
        return {"ok": False, "reason": "ev_api_key_missing"}
    if _budget_left() <= 0:
        # 재시도해도 소용없다 — 날짜가 바뀌어야 풀린다.
        return {"ok": False, "reason": "daily_budget_exhausted"}

    targets = await refresh_targets()
    if not targets:
        return {"ok": False, "reason": "no_targets"}

    rows = await ev_stations.fetch_status_feed()
    _spend(max(1, len(rows) // 9999 + 1))  # 페이지 수 ≈ 호출 수

    seen: set[tuple[str, str, datetime]] = set()
    pending: list[tuple[str, str, datetime, datetime]] = []
    for row in rows:
        sid = row.get("statId")
        if not sid or sid not in targets:
            continue
        started = _parse_kst(row.get("lastTsdt", ""))
        ended = _parse_kst(row.get("lastTedt", ""))
        if started is None or ended is None:
            continue
        minutes = (ended - started).total_seconds() / 60.0
        if not (_MIN_SESSION_MIN <= minutes <= _MAX_SESSION_MIN):
            continue
        cid = row.get("chgerId") or "?"
        key = (sid, cid, started)
        if key in seen:  # 같은 응답 안의 중복 방지(executemany는 자기충돌을 못 막는다)
            continue
        seen.add(key)
        pending.append((sid, cid, started, ended))

    if pending:
        async with p.acquire() as conn:
            # ON CONFLICT DO NOTHING — 5분 폴링이 10분 윈도를 2배로 겹쳐 읽으므로
            # 대부분의 행은 이미 들어있는 세션이다. 그게 정상이고 비용도 없다.
            # (executemany는 적재 건수를 돌려주지 않는다. 신규 건수가 알고 싶으면
            #  아래 sessions_seen이 아니라 /internal/aggregate의 통계를 보면 된다.)
            await conn.executemany(
                """
                INSERT INTO session (station_id, charger_id, started_at, ended_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (station_id, charger_id, started_at) DO NOTHING
                """,
                pending,
            )

    return {
        "ok": True,
        "feed_rows": len(rows),
        "targets": len(targets),
        "sessions_seen": len(pending),  # 신규 + 중복 (중복은 무시됨)
        "budget_left": _budget_left(),
    }
