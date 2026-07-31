"""전기차 충전소 정보 서비스.

PPT 기획 4번: 충전소명 / 충전기 종류 / 제휴카드 / 멤버쉽가입유무 / 실시간충전현황.

EV_STATION_API_KEY(공공데이터포털 - 한국환경공단_전기자동차 충전소 정보)가 있으면
실제 API를, 없으면 목(mock) 데이터를 사용한다.

  - getChargerInfo : 충전소/충전기 정보 (statNm, chgerType, lat, lng, stat, ...)
  - 조회는 zcode(시도코드) 단위. 경로가 지나는 시도들을 조회해 경로 인근만 필터.

주의:
  * serviceKey 는 공공데이터포털의 "디코딩(Decoding) 키"를 .env 에 넣어야 한다
    (httpx 가 인코딩하므로 인코딩 키를 넣으면 이중 인코딩되어 실패).
  * '제휴카드'/'잔여시간'은 공공 API가 제공하지 않아 각각 기본값/None 으로 둔다.
  * '멤버쉽가입유무'는 API의 limitYn(이용자 제한) 을 근사값으로 사용.
"""

from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable

import httpx

from ..config import settings
from ..http import QuotaExceeded, RateLimited, client as _http
from ..models import (
    LatLng,
    RealtimeCharger,
    StationDetail,
    StationSummary,
)
from . import kakao
from .charging import _haversine_km, bbox_deg as _bbox_deg, sample_path_points

# 공공데이터포털이 HTTPS를 지원하므로 HTTP 대신 HTTPS 사용(전송구간 보호)
EV_API_BASE = "https://apis.data.go.kr/B552584/EvCharger"

# 충전기 상태코드(stat) → 표시 상태. 2:충전대기 3:충전중 4:운영중지 5:점검중 1/9:미확인
_STAT_LABELS = {
    "1": "상태미확인",
    "2": "충전가능",
    "3": "충전중",
    "4": "운영중지",
    "5": "점검중",
    "9": "상태미확인",
}
_DEFAULT_STATUS = "상태미확인"
# 충전기 타입(chgerType): 02=AC완속 → 완속, 그 외 → 급속 (일반적 단순화)
_SLOW_TYPES = {"02"}
# 충전기 커넥터(chgerType 코드 → 커넥터 명). 없는 코드는 빈 문자열(화면에서 제외).
_CONNECTOR_NAMES = {
    "01": "DC차데모",
    "02": "AC완속",
    "03": "DC차데모+AC3상",
    "04": "DC콤보",
    "05": "DC차데모+DC콤보",
    "06": "DC차데모+AC3상+DC콤보",
    "07": "AC3상",
    "08": "DC콤보(완속)",
    "89": "수소",
}
# 결제 수단은 공공 API 미제공 → 기본값(환경부 로밍 '전기차이음' 등 공통 결제 카드)
_DEFAULT_PAYMENT_METHODS = ["환경부통합", "EV CHARGE"]
# 충전 출력(kW) 기본값 — API output 필드가 없을 때 타입별로 사용
_DEFAULT_POWER_KW = {"급속": 100.0, "완속": 7.0}
# 단가(원/kWh) — 공공 API 미제공, 타입별 기본값(환경부 회원 기준). 필요 시 조정.
_UNIT_PRICE = {"급속": 347.2, "완속": 292.9}

# 조회 튜닝: numOfRows를 크게 잡아 시도당 호출 수를 최소화(429 예방)
_ROWS = 9999
# 위치 카탈로그 TTL. 계획 응답시간의 절반 이상(400km 기준 24개 시군구 ≈ 4.5초)이
# 이 카탈로그를 받는 데 쓰이므로, 캐시가 살아있는 동안은 계획이 몇 배 빨라진다.
# 담는 내용이 충전소 위치·이름·출력·개방여부 같은 '거의 안 변하는 메타데이터'라
# 24시간으로 늘려도 정확도 손실이 사실상 없다(신규 충전소 반영이 최대 하루 늦어질 뿐).
# 실시간 사용가능 여부는 아래 _STATUS_TTL(20초) 캐시가 따로 담당하므로 영향 없음.
_CATALOG_TTL = 24 * 3600.0
_STATUS_TTL = 20.0  # 상세 실시간 상태: 단기 캐시(상세 진입 시에만 실시간)
_THROTTLE_SEC = 0.4  # 연속 페이지 호출 간 지연(429 예방)
_MAX_RETRY = 3
# 콜드 카탈로그 빌드 시 동시 호출 상한. 실측상 8 이상이면 공공 API가 곧바로
# 호출초과로 차단한다(4는 정상) → 올리면 오히려 계획이 실패한다. 건드리지 말 것.
_FETCH_CONCURRENCY = 4
_fetch_sem = asyncio.Semaphore(_FETCH_CONCURRENCY)
# Kakao 좌표→행정동 변환 동시 호출 상한. 장거리 경로는 샘플 지점이 30개+라
# 무제한 gather 시 Kakao 순간호출 제한(버스트 스로틀)에 걸린다 → 6개로 완만화.
_KAKAO_CONCURRENCY = 6
_kakao_sem = asyncio.Semaphore(_KAKAO_CONCURRENCY)

# 위치 카탈로그: zcode → (ts, 충전소 목록). 상태는 여기 포함 안 함.
_catalog_cache: dict[str, tuple[float, list[StationSummary]]] = {}
# 진행 중인 카탈로그 조회(시군구별). 동시 요청이 같은 조회를 공유해 중복 호출을 막는다.
_catalog_inflight: dict[str, "asyncio.Task[list[StationSummary]]"] = {}
# 실시간 상태: "zcode:zscode" → (ts, 원본 로우). 상세 진입 시에만 채움.
_status_cache: dict[str, tuple[float, list[dict]]] = {}
# statId → (zcode, zscode). 카탈로그 조회 시 채워, 상세를 시군구 단위로 좁힘.
_station_region: dict[str, tuple[str, str]] = {}


def _charge_type(code: str) -> str:
    return "완속" if code in _SLOW_TYPES else "급속"


def _connector_name(code: str) -> str | None:
    """chgerType 코드 → 커넥터 명. 미확인 코드는 None(화면에서 제외)."""
    return _CONNECTOR_NAMES.get((code or "").strip()) or None


# 이용제한(limitDetail) 분류 키워드
# 방문객/고객 명시는 외부인 사용 가능 신호 → 입주·관계자 키워드보다 우선한다
# ('입주사 방문객', '입주민 방문객'처럼 방문객은 쓸 수 있는데 과차단되던 문제 해소).
_VISITOR_KW = ("방문객", "고객", "이용객", "이용고객", "투숙")
_RESIDENT_KW = ("입주민", "거주자", "입주자", "입주사", "세대", "공동주택", "아파트", "빌라")
_STAFF_KW = ("임직원", "직원", "관계자", "사전차량", "비개방", "출입불가", "외부인 이용제한", "외부인 출입제한")
# 특정 차종/집단 전용 — 일반 승용 EV(돌핀)가 실제로 충전 못 함. 추천되면 도착 후
# 충전불가 = 방전위험이므로 '사용불가'로 분류(주행안정성).
_FLEET_KW = ("전기버스", "화물차", "택시", "카셰어링", "카쉐어링", "쏘카", "그린카",
             "관용", "공무", "경찰", "소방", "군부대", "이륜")


def _access_class(limit_yn: str, limit_detail: str) -> str:
    """이용 접근성 분류: open/open_fee(외부인 가능) / residents/staff/fleet(불가)."""
    if (limit_yn or "").upper() != "Y":
        return "open"
    t = limit_detail or ""
    if any(k in t for k in _VISITOR_KW):
        return "open_fee"  # 방문객/고객 허용 → 외부인 이용가능(입주·관계자보다 우선)
    if any(k in t for k in _RESIDENT_KW):
        return "residents"  # 거주건물 — 외부인 불가
    if any(k in t for k in _STAFF_KW):
        return "staff"  # 관계자 전용 — 외부인 불가
    if any(k in t for k in _FLEET_KW):
        return "fleet"  # 특정 차종/집단 전용 — 승용 EV 사용 불가
    return "open_fee"  # 고객/시설/조건부 — 외부인 이용가능(주차비 발생 가능)


def _output_kw(output: str | None, charge_type: str) -> float:
    """API output(kW) 파싱, 없으면 타입별 기본값."""
    try:
        kw = float(output) if output else 0.0
        return kw if kw > 0 else _DEFAULT_POWER_KW[charge_type]
    except ValueError:
        return _DEFAULT_POWER_KW[charge_type]


# data.go.kr 쿼터 소진 신호. 두 가지 형태로 온다(실측 확인).
#   (a) HTTP 200 + XML  returnReasonCode 22 = LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR
#   (b) HTTP 429 + text/plain  "API token quota exceeded"   ← 게이트웨이 레벨
# (b)를 상태코드만 보고 '일시적 과다호출'로 처리하면, 실제로는 그날 회복되지 않는데
# "잠시 후 다시 시도"라고 잘못 안내하게 된다 → 본문까지 확인해 구분한다.
_QUOTA_MARKERS = (
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS",
    "<returnReasonCode>22",
    "<resultCode>22",
    "quota exceeded",
)


def _is_quota_body(text: str) -> bool:
    low = text.lower()
    return any(m.lower() in low for m in _QUOTA_MARKERS)


async def _get_with_retry(params: dict) -> httpx.Response:
    """공유 클라이언트로 조회. 429는 백오프 재시도하되, 쿼터 소진이면 즉시 중단."""
    for attempt in range(_MAX_RETRY):
        r = await _http().get(f"{EV_API_BASE}/getChargerInfo", params=params, timeout=20)
        if r.status_code == 429:
            # 쿼터 소진은 재시도해도 소용없다 → 백오프 낭비 없이 즉시 알린다.
            if _is_quota_body(r.text):
                raise QuotaExceeded("ev")
            if attempt < _MAX_RETRY - 1:
                await asyncio.sleep(0.6 * (attempt + 1))
                continue
            raise RateLimited("ev")  # 본문에 근거 없는 429 = 단시간 과다호출
        r.raise_for_status()
        return r
    raise RateLimited("ev")  # 방어적(도달 불가)


async def _fetch_rows(zcode: str, zscode: str | None = None) -> list[dict]:
    """zcode(+선택적 zscode) 범위의 충전기 로우 전체를 조회.

    numOfRows를 크게 잡아 페이지 수를 최소화하고, 페이지 사이에 스로틀을 둔다.
    응답 본문에 호출초과(코드22) 신호가 있으면 QuotaExceeded로 구분해 던진다.
    """
    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "serviceKey": settings.ev_station_api_key,
            "pageNo": page,
            "numOfRows": _ROWS,
            "zcode": zcode,
        }
        if zscode:
            params["zscode"] = zscode
        r = await _get_with_retry(params)
        if _is_quota_body(r.text):
            raise QuotaExceeded("ev")  # HTTP 200 본문에 담겨오는 쿼터 소진
        root = ET.fromstring(r.text)
        page_items = root.findall(".//item")
        for it in page_items:
            rows.append({c.tag: (c.text or "").strip() for c in it})
        total_el = root.find(".//totalCount")
        total = int(total_el.text) if total_el is not None and total_el.text else 0
        if page * _ROWS >= total or not page_items:
            break
        page += 1
        await asyncio.sleep(_THROTTLE_SEC)
    return rows


async def _fetch_catalog(key: str, zcode: str, zscode: str) -> list[StationSummary]:
    """실제 카탈로그 조회 + 캐시 적재 (in-flight 공유 대상)."""
    async with _fetch_sem:  # 동시 호출 상한
        rows = await _fetch_rows(zcode, zscode)
    now = time.monotonic()
    stations = list(_group_stations(rows).values())
    for row in rows:  # 상세를 시군구 단위로 좁히기 위한 매핑
        sid = row.get("statId")
        if sid:
            _station_region[sid] = (zcode, row.get("zscode", zscode))
    _catalog_cache[key] = (now, stations)
    # 방금 받은 로우로 상태캐시도 채운다 → 콜드 계획에서 같은 시군구를 상태용으로
    # 다시 fetch하는 중복 호출을 없앤다(로우는 방금 받아 신선). 상태캐시는 20초라
    # 이후엔 정상적으로 실시간 재조회된다.
    _status_cache[key] = (now, rows)
    return stations


async def _get_catalog(zcode: str, zscode: str) -> list[StationSummary]:
    """시군구(zcode+zscode) 위치 카탈로그 — 장기 캐시. 상태는 포함하지 않는다.

    같은 시군구를 동시에 요청하면(예: 워밍업과 사용자 계산이 겹칠 때) 하나의 조회를
    공유한다. 없으면 같은 데이터를 중복으로 받아 응답도 느려지고 API 쿼터도 두 배로
    쓴다(400km 경로 하나가 시군구 20여 개를 부르므로 체감이 크다).

    공유 Task는 shield로 감싸 await 한다. 맨 await로 기다리면 **대기자 한 명의 취소가
    Task 자체로 전파**되어, 같은 시군구를 기다리던 무관한 요청까지 CancelledError로
    죽는다(asyncio 수준에서 재현됨 — test_external_stability.py 9번).

    다만 현재 스택에서는 이 취소가 요청 경로로는 들어오지 않는다. 실측(2026-08-01,
    starlette 1.3.1 / uvicorn 0.51.0 / fastapi 0.139.2): **클라이언트가 연결을 끊어도
    핸들러는 취소되지 않고 끝까지 실행된다.** 즉 프런트 타임아웃·화면 이탈로는 이
    버그가 발현되지 않는다. 지금은 방어적 조치이고, 트리거는 서버 종료(재배포) 정도다.
    starlette가 연결 끊김 시 취소 동작을 바꾼 이력이 있어(버전마다 다름) 업그레이드
    후 다시 도달 가능해질 수 있으므로 shield는 유지한다 — 비용이 없다.
    """
    key = f"{zcode}:{zscode}"
    cached = _catalog_cache.get(key)
    if cached and time.monotonic() - cached[0] < _CATALOG_TTL:
        return cached[1]

    inflight = _catalog_inflight.get(key)
    if inflight is None:
        inflight = asyncio.create_task(_fetch_catalog(key, zcode, zscode))
        _catalog_inflight[key] = inflight
        # 정리는 완료 콜백으로 — 대기자가 몇 명이든, 누가 취소되든 정확히 한 번 돈다.
        # (예전처럼 '주인'의 finally에서 지우면, 주인이 취소됐을 때 아직 살아 있는
        #  Task의 항목이 사라져 뒤이은 요청이 중복 조회를 시작한다.)
        inflight.add_done_callback(_make_inflight_release(key))
    return await asyncio.shield(inflight)  # 진행 중인 동일 조회에 편승


def _make_inflight_release(key: str):
    """in-flight 항목 정리 콜백. 미회수 예외 경고도 함께 막는다."""

    def _release(task: "asyncio.Task[list[StationSummary]]") -> None:
        _catalog_inflight.pop(key, None)
        # 대기자가 전부 취소된 뒤 Task가 예외로 끝나면 "Task exception was never
        # retrieved" 경고가 뜬다. 여기서 한 번 읽어 소비한다(로그 노이즈 제거).
        if not task.cancelled():
            task.exception()

    return _release


def _evict_expired_status(now: float) -> None:
    """만료된 상태캐시 제거.

    _status_cache는 시군구 원본 로우(건당 ~2.5KB)를 통째로 들고 있어, 장거리 경로
    1회 계산만으로 수십~수백 MB가 상주한다. TTL은 '읽을 때 만료 판정'만 하므로
    엔트리 자체를 지워주지 않으면 프로세스가 살아있는 동안 계속 쌓인다.
    """
    for k, (ts, _) in list(_status_cache.items()):
        if now - ts >= _STATUS_TTL:
            del _status_cache[k]


async def _status_rows(zcode: str, zscode: str | None) -> list[dict]:
    """상세용 실시간 상태 로우 — 시군구 단위 단기 캐시."""
    key = f"{zcode}:{zscode or ''}"
    now = time.monotonic()
    _evict_expired_status(now)
    cached = _status_cache.get(key)
    if cached and now - cached[0] < _STATUS_TTL:
        return cached[1]
    rows = await _fetch_rows(zcode, zscode or None)
    _status_cache[key] = (now, rows)
    return rows


def _group_stations(rows: list[dict]) -> dict[str, StationSummary]:
    """충전기 로우를 statId 기준 충전소로 묶는다."""
    stations: dict[str, StationSummary] = {}
    for row in rows:
        sid = row.get("statId")
        lat, lng = row.get("lat"), row.get("lng")
        if not sid or not lat or not lng:
            continue
        ctype = _charge_type(row.get("chgerType", ""))
        power = _output_kw(row.get("output"), ctype)
        if sid not in stations:
            # 접근성은 카탈로그 로우에 이미 들어있어 추가 API 호출 없이 판정된다.
            # 입주민/관계자/특정차량 전용은 애초에 충전계획 후보에서 빼기 위한 표시.
            access = _access_class(row.get("limitYn", "N"), row.get("limitDetail", ""))
            stations[sid] = StationSummary(
                id=sid,
                name=row.get("statNm", sid),
                location=LatLng(lat=float(lat), lng=float(lng)),
                charger_types=[ctype],
                max_power_kw=power,
                public_access=access in ("open", "open_fee"),
            )
        else:
            if ctype not in stations[sid].charger_types:
                stations[sid].charger_types.append(ctype)
            if power > stations[sid].max_power_kw:
                stations[sid].max_power_kw = power
    return stations


async def _districts_for_path(
    path: list[LatLng], samples: int = 16
) -> list[tuple[str, str]]:
    """경로가 지나는 시군구 (zcode, zscode) 집합.

    경로를 일정 간격으로 샘플링해 각 지점의 법정동 코드를 얻고,
    앞 2자리(시도)·앞 5자리(시군구)로 잘라 중복 제거한다.
    """
    if not path:
        return []
    # 거리 기준 샘플(정점 인덱스 기준은 고속도로에서 시군구를 놓침). 약 12km 간격.
    points = sample_path_points(path, 12.0)

    # 좌표→코드 변환을 병렬로 하되 동시 호출은 상한(_kakao_sem). 무제한이면 장거리에서
    # 30개+ 요청이 한꺼번에 나가 Kakao 버스트 스로틀에 걸린다.
    async def _bounded_region(p: LatLng) -> str | None:
        async with _kakao_sem:
            return await kakao.region_code(p)

    codes = await asyncio.gather(*(_bounded_region(p) for p in points))
    districts: list[tuple[str, str]] = []
    for code in codes:
        if code and len(code) >= 5:
            d = (code[:2], code[:5])
            if d not in districts:
                districts.append(d)
    return districts


async def stations_near_path(path: list[LatLng], radius_km: float = 12.0) -> list[StationSummary]:
    """경로 좌표열에서 radius_km 이내의 충전소 목록 (시군구 카탈로그, 장기 캐시)."""
    if settings.use_ev_api:
        try:
            districts = await _districts_for_path(path)
            catalogs = await asyncio.gather(
                *(_get_catalog(z, zs) for z, zs in districts)
            )
            # 입주민·관계자·특정차량 전용은 충전계획 후보에서 아예 제외한다.
            # (계획을 세운 뒤 '사용불가'로 표시만 하면, 정작 계획의 중심이 못 쓰는
            #  충전소가 되어 대체소를 찾느라 경로가 흔들린다.)
            stations = [st for cat in catalogs for st in cat if st.public_access]
            # 근접 판정용 경로 샘플(거리 기준 ~2km 간격 → 반경 판정 공백 없음)
            sparse = sample_path_points(path, 2.0)
            # 경로에서 먼 충전소는 샘플 전체(수백 개)에 대해 haversine을 다 돌게 되어
            # 카탈로그가 커지면 초 단위로 느려진다 → 삼각함수 없는 사각박스로 먼저 컷.
            dlat, dlng = _bbox_deg(radius_km)
            near = [
                st
                for st in stations
                if any(
                    abs(pt.lat - st.location.lat) <= dlat
                    and abs(pt.lng - st.location.lng) <= dlng
                    and _haversine_km(pt, st.location) <= radius_km
                    for pt in sparse
                )
            ]
            if near:
                return near
        except (httpx.HTTPError, ET.ParseError, ValueError):
            pass  # 실패 시(mock_enabled면) 목으로 폴백

    # 실데이터 모드에서는 목 충전소로 폴백하지 않는다(실제로 없는 충전소 추천 방지).
    if not settings.mock_enabled:
        return []

    return [
        st
        for st in _MOCK_STATIONS
        if any(_haversine_km(pt, st.location) <= radius_km for pt in path)
    ]


async def get_station_detail(station_id: str) -> StationDetail | None:
    """충전소 상세 + 실시간 충전현황."""
    if settings.use_ev_api:
        region = _station_region.get(station_id)
        if region is not None:
            zcode, zscode = region
            try:
                rows = [
                    r
                    for r in await _status_rows(zcode, zscode)
                    if r.get("statId") == station_id
                ]
                if rows:
                    return _build_detail(rows)
            except (httpx.HTTPError, ET.ParseError, ValueError):
                pass  # 실패 시(mock_enabled면) 목으로 폴백

    # 실데이터 모드에서는 목 상세로 폴백하지 않는다.
    if not settings.mock_enabled:
        return None

    summary = next((s for s in _MOCK_STATIONS if s.id == station_id), None)
    if summary is None:
        return None
    d = _MOCK_DETAIL.get(station_id) or _default_detail(summary)
    return StationDetail(
        id=summary.id,
        name=summary.name,
        location=summary.location,
        charger_types=summary.charger_types,
        payment_methods=d["payment_methods"],
        usage_restricted=d["usage_restricted"],
        limit_detail=d.get("limit_detail", ""),
        parking_free=d.get("parking_free", True),
        business_name=d.get("business_name"),
        address=d.get("address"),
        use_time=d.get("use_time"),
        install_year=d.get("install_year"),
        chargers=d["chargers"],
        data_source="mock",
    )


def _availability(detail: StationDetail) -> tuple[bool, str]:
    """상세 → (외부인 사용가능 여부, 사유).

    거주/관계자 전용은 외부인 불가. 그 외(개방·고객/시설)는 충전기 상태로 판단,
    유료주차면 '외부인 이용가능(주차비 발생)'으로 표기.
    """
    access = _access_class("Y" if detail.usage_restricted else "N", detail.limit_detail)
    if access == "residents":
        return False, "입주민전용"
    if access == "staff":
        return False, "관계자전용"
    if access == "fleet":
        return False, "특정차량 전용"
    # 외부인 이용 가능(open/open_fee) → 충전기 운영상태로 판단
    if not any(c.status in ("충전가능", "충전중") for c in detail.chargers):
        for reason in ("점검중", "운영중지"):
            if any(c.status == reason for c in detail.chargers):
                return False, reason
        return False, "상태미확인"
    if access == "open_fee":
        return True, "외부인 이용가능(주차비 발생)" if not detail.parking_free else "외부인 이용가능"
    return True, "사용가능"


async def station_availability(station_id: str) -> tuple[bool, str] | None:
    """충전소 실시간 사용가능 여부. (available, reason) 또는 None."""
    detail = await get_station_detail(station_id)
    if detail is None:
        return None
    return _availability(detail)


async def warm_status(station_ids: Iterable[str]) -> None:
    """주어진 충전소들의 시군구 실시간 상태를 병렬 프리페치(시군구 중복은 1회).

    경로 계획에서 목적지·배정·대체 충전소 상태를 순차로 조회하면 시군구마다
    네트워크 왕복이 쌓여 느리다. 필요한 시군구 상태를 미리 한 번에 데워두면
    이후 station_availability() 호출이 모두 캐시 히트가 되어 순차 루프의 대기가
    사라진다. 공공 API 429 방지를 위해 _fetch_sem으로 동시 호출을 제한한다.
    """
    if not settings.use_ev_api:
        return
    districts = {
        _station_region[sid] for sid in station_ids if sid in _station_region
    }
    if not districts:
        return

    async def _one(zcode: str, zscode: str) -> None:
        async with _fetch_sem:  # 동시 호출 상한(429 예방)
            try:
                await _status_rows(zcode, zscode)  # 캐시 미스일 때만 실제 fetch
            except (httpx.HTTPError, ET.ParseError, ValueError):
                pass  # 개별 시군구 실패는 무시(해당 지점은 상태미확인 처리됨)

    await asyncio.gather(*(_one(z, zs) for z, zs in districts))


def _build_detail(rows: list[dict]) -> StationDetail:
    """동일 statId 로우들 → 충전소 상세 (실시간 충전현황 포함)."""
    first = rows[0]
    chargers = []
    for row in rows:
        ctype = _charge_type(row.get("chgerType", ""))
        chargers.append(
            RealtimeCharger(
                charger_no=row.get("chgerId", "?"),
                charge_type=ctype,
                connector=_connector_name(row.get("chgerType", "")),
                status=_STAT_LABELS.get(row.get("stat", ""), _DEFAULT_STATUS),
                remaining=None,  # 공공 API는 잔여시간 미제공
                power_kw=_output_kw(row.get("output"), ctype),
                unit_price=_UNIT_PRICE[ctype],
                # 회원/비회원 요금은 공공 API 미제공 → None(화면에서 제외)
            )
        )
    types: list[str] = []
    for c in chargers:
        if c.charge_type not in types:
            types.append(c.charge_type)
    addr = " ".join(
        p for p in (first.get("addr", ""), first.get("addrDetail", "")) if p
    ).strip()
    return StationDetail(
        id=first["statId"],
        name=first.get("statNm", first["statId"]),
        location=LatLng(lat=float(first["lat"]), lng=float(first["lng"])),
        charger_types=types,
        payment_methods=_DEFAULT_PAYMENT_METHODS,
        usage_restricted=first.get("limitYn", "N") == "Y",
        limit_detail=first.get("limitDetail", "").strip(),
        parking_free=first.get("parkingFree", "Y").upper() != "N",
        business_name=(first.get("busiNm") or first.get("bnm") or "").strip() or None,
        address=addr or None,
        use_time=(first.get("useTime", "").strip() or None),
        install_year=(first.get("year", "").strip() or None),
        chargers=chargers,
        data_source="public_api",
    )


# --------------------------------------------------------------------------
# 목(mock) 데이터 — 키가 없거나 API 실패 시 사용
# --------------------------------------------------------------------------
_MOCK_STATIONS: list[StationSummary] = [
    StationSummary(id="ST001", name="경기중앙충전", location=LatLng(lat=37.30, lng=127.05), charger_types=["급속", "완속"]),
    StationSummary(id="ST002", name="안성휴게소충전", location=LatLng(lat=37.00, lng=127.18), charger_types=["급속"]),
    StationSummary(id="ST003", name="천안삼거리충전소", location=LatLng(lat=36.80, lng=127.15), charger_types=["급속", "완속"]),
    StationSummary(id="ST004", name="대전신탄진충전", location=LatLng(lat=36.47, lng=127.42), charger_types=["급속"]),
    StationSummary(id="ST005", name="대전유성충전소", location=LatLng(lat=36.35, lng=127.34), charger_types=["급속", "완속"]),
    StationSummary(id="ST006", name="옥천IC충전", location=LatLng(lat=36.30, lng=127.57), charger_types=["급속"]),
    StationSummary(id="ST007", name="김천구미충전소", location=LatLng(lat=36.12, lng=128.32), charger_types=["급속", "완속"]),
    StationSummary(id="ST008", name="대구북부충전", location=LatLng(lat=35.90, lng=128.60), charger_types=["급속"]),
]

# 회원/비회원 요금 예시값(원/kWh) — 목 데모용. 실제 공공 API는 요금 미제공.
_MOCK_PRICE = {"급속": (347.2, 460.0), "완속": (292.9, 360.0)}


def _mock_charger(no: str, ctype: str, status: str, remaining: str | None) -> RealtimeCharger:
    m, nm = _MOCK_PRICE[ctype]
    return RealtimeCharger(
        charger_no=no,
        charge_type=ctype,
        connector=("DC콤보" if ctype == "급속" else "AC완속"),
        status=status,
        remaining=remaining,
        power_kw=_DEFAULT_POWER_KW[ctype],
        unit_price=_UNIT_PRICE[ctype],
        price_member=m,
        price_nonmember=nm,
    )


_MOCK_DETAIL: dict[str, dict] = {
    "ST001": {
        "payment_methods": ["환경부통합", "EV CHARGE"],
        "usage_restricted": True,
        "limit_detail": "입주민 전용",
        "parking_free": True,
        "business_name": "한국전력공사",
        "address": "경기도 성남시 분당구 미금로 100",
        "use_time": "24시간 이용가능",
        "install_year": "2021",
        "chargers": [
            _mock_charger("1", "급속", "충전중", "1시간1분"),
            _mock_charger("2", "완속", "충전가능", None),
        ],
    }
}


def _default_detail(s: StationSummary) -> dict:
    chargers = [
        _mock_charger(
            str(i + 1), t, ("충전중" if i % 2 == 1 else "충전가능"),
            ("15분" if i % 2 == 1 else None),
        )
        for i, t in enumerate(s.charger_types)
    ]
    return {
        "payment_methods": ["환경부통합", "EV CHARGE"],
        "usage_restricted": False,
        "limit_detail": "",
        "parking_free": True,
        "business_name": "환경부",
        "address": "",
        "use_time": "24시간 이용가능",
        "install_year": "2022",
        "chargers": chargers,
    }
