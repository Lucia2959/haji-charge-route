"""Kakao Mobility(경로) / Local(주소검색) API 클라이언트.

KAKAO_REST_API_KEY 가 없으면 목(mock) 데이터로 동작하여 키 없이도 앱이 구동된다.
"""

from __future__ import annotations

import asyncio

import httpx

from ..config import settings
from ..http import RateLimited, client as _http
from ..models import LatLng, PlaceResult

# 외부기관(Kakao) 연계 안정성: 순간 429·5xx·네트워크 오류에 즉시 실패하면 전체
# 경로가 mock으로 붕괴한다. EV API(_get_with_retry)와 동일하게 지수백오프 재시도로
# 일시적 장애를 흡수한다. 비재시도성(4xx 등)은 그대로 반환 → 호출부가 처리.
_MAX_RETRY = 3


async def _get_retry(url: str, **kwargs) -> httpx.Response:
    """Kakao GET — 공유 클라이언트 사용, 429·5xx·타임아웃/전송오류 시 지수백오프 재시도.

    재시도해도 지속 429면 RateLimited(단시간 과다호출)로 구분해 던진다. 카카오는
    쿼터 소진과 순간 스로틀을 모두 429로 주므로, 사용자에겐 '잠시 후 재시도'가
    양쪽 모두에 맞는 안내다.
    """
    for attempt in range(_MAX_RETRY):
        try:
            r = await _http().get(url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == _MAX_RETRY - 1:
                raise  # 마지막까지 실패 → 상위에서 mock 폴백(network 오류)
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        if r.status_code == 429:
            if attempt < _MAX_RETRY - 1:
                await asyncio.sleep(0.5 * (attempt + 1))  # 일시 제한 → 재시도
                continue
            raise RateLimited("kakao")  # 지속 429 → 단시간 과다호출
        if r.status_code >= 500 and attempt < _MAX_RETRY - 1:
            await asyncio.sleep(0.5 * (attempt + 1))  # 서버오류 → 재시도
            continue
        return r  # 성공(2xx) 또는 비재시도성 응답(4xx는 호출부 raise_for_status가 처리)


class LocationNotFound(Exception):
    """주소·지명을 좌표로 변환하지 못했을 때 발생 (실데이터 모드)."""


class RouteUnavailable(Exception):
    """실제 도로 경로를 조회하지 못했을 때 발생 (실데이터 모드)."""

# 목 지오코딩용 주요 지명 좌표 (키가 없을 때만 사용)
_MOCK_PLACES: dict[str, LatLng] = {
    "서울": LatLng(lat=37.5665, lng=126.9780),
    "서울역": LatLng(lat=37.5559, lng=126.9723),
    "강남": LatLng(lat=37.4979, lng=127.0276),
    "수원": LatLng(lat=37.2636, lng=127.0286),
    "대전": LatLng(lat=36.3504, lng=127.3845),
    "대구": LatLng(lat=35.8714, lng=128.6014),
    "부산": LatLng(lat=35.1796, lng=129.0756),
    "광주": LatLng(lat=35.1595, lng=126.8526),
    "강릉": LatLng(lat=37.7519, lng=128.8761),
}


def _parse_lnglat(text: str) -> LatLng | None:
    if "," in text:
        try:
            a, b = (float(x) for x in text.split(",")[:2])
            # "lng,lat" 우선(카카오 관례), 위경도 범위로 판별
            if abs(a) <= 180 and abs(b) <= 90:
                return LatLng(lat=b, lng=a)
        except ValueError:
            return None
    return None


async def geocode(text: str) -> LatLng:
    """주소·지명을 좌표로 변환. 'lng,lat' 문자열도 허용."""
    direct = _parse_lnglat(text)
    if direct:
        return direct

    if settings.use_kakao:
        headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
        r = await _get_retry(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            headers=headers,
            params={"query": text, "size": 1},
            timeout=10,
        )
        r.raise_for_status()
        docs = r.json().get("documents", [])
        if docs:
            return LatLng(lat=float(docs[0]["y"]), lng=float(docs[0]["x"]))

    # 실데이터 모드에서는 못 찾으면 오류 — 잘못된 주소가 서울로 계산되는 것을 막는다.
    if not settings.mock_enabled:
        raise LocationNotFound(text)

    # 목 폴백 (mock_enabled일 때만): 대표 지명 사전, 무매칭 시 서울
    for name, loc in _MOCK_PLACES.items():
        if name in text:
            return loc
    return _MOCK_PLACES["서울"]


async def search_places(query: str, size: int = 10) -> list[PlaceResult]:
    """키워드로 장소 검색 (출발지·도착지 주소 팝업). 키 없으면 목 결과."""
    query = query.strip()
    if not query:
        return []

    if settings.use_kakao:
        headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
        r = await _get_retry(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            headers=headers,
            params={"query": query, "size": size},
            timeout=10,
        )
        r.raise_for_status()
        return [
            PlaceResult(
                name=d.get("place_name", query),
                address=d.get("road_address_name") or d.get("address_name", ""),
                location=LatLng(lat=float(d["y"]), lng=float(d["x"])),
            )
            for d in r.json().get("documents", [])
        ]

    # 목 폴백: 주요 지명 사전에서 부분일치
    results: list[PlaceResult] = []
    for name, loc in _MOCK_PLACES.items():
        if query in name or name in query:
            results.append(PlaceResult(name=name, address=f"{name} (목 데이터)", location=loc))
    if not results:  # 무매칭 시 대표 후보 제공
        results = [
            PlaceResult(name=n, address=f"{n} (목 데이터)", location=loc)
            for n, loc in list(_MOCK_PLACES.items())[:5]
        ]
    return results


async def region_code(loc: LatLng) -> str | None:
    """좌표 → 법정동 코드(10자리). 앞 2자리=시도(zcode), 앞 5자리=시군구(zscode).

    전기차 충전소 API의 zcode/zscode 파라미터에 사용. 강원/전북 특별자치도 등
    코드 변경도 자동 반영된다. 카카오 키가 없으면 None.
    """
    if not settings.use_kakao:
        return None
    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
    r = await _get_retry(
        "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
        headers=headers,
        params={"x": loc.lng, "y": loc.lat},
        timeout=10,
    )
    r.raise_for_status()
    docs = r.json().get("documents", [])
    # 법정동('B') 우선, 없으면 첫 문서
    doc = next((d for d in docs if d.get("region_type") == "B"), None) or (
        docs[0] if docs else None
    )
    if doc and doc.get("code"):
        return str(doc["code"])
    return None


# 고속도로/자동차전용 도로 판정 키워드 (도로명 기반)
_HIGHWAY_ROAD_KW = ("고속도로", "고속화도로", "자동차전용")


def _road_class(name: str | None, speed_kmh: float) -> str:
    """도로 등급 — "highway"(고속도로) / "expressway"(자동차전용) / "local".

    등급을 bool(고속도로 여부) 대신 문자열로 두는 이유: 법정 제한속도가 등급마다
    다르기 때문이다(고속도로 50~110, 자동차전용 30~90). 카카오 경로 응답에는
    제한속도 필드가 없어 등급으로 근사할 수밖에 없다 — charging.SPEED_LIMITS 참고.

    이름만으로는 도시고속(강변북로 등)을 놓치므로 실제 주행속도도 함께 본다.
    이름 없이 속도만으로 잡힌 구간은 고속도로로 단정할 수 없어 자동차전용으로 둔다.
    """
    n = name or ""
    if "고속도로" in n:
        return "highway"
    if any(k in n for k in ("고속화도로", "자동차전용")):
        return "expressway"
    return "expressway" if speed_kmh >= 85.0 else "local"


def _interpolate(origin: LatLng, dest: LatLng, n: int = 24) -> list[LatLng]:
    return [
        LatLng(
            lat=origin.lat + (dest.lat - origin.lat) * i / n,
            lng=origin.lng + (dest.lng - origin.lng) * i / n,
        )
        for i in range(n + 1)
    ]


async def get_directions(origin: LatLng, dest: LatLng) -> dict:
    """경로 조회 → {distance_km, duration_min, path[LatLng]}."""
    if settings.use_kakao:
        headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
        r = await _get_retry(
            "https://apis-navi.kakaomobility.com/v1/directions",
            headers=headers,
            params={
                "origin": f"{origin.lng},{origin.lat}",
                "destination": f"{dest.lng},{dest.lat}",
                "priority": "RECOMMEND",
                "roadevent": 2,  # 유고(교통장애) 미반영 → 출발지 유고로 경로 거부(105) 방지
            },
            timeout=15,
        )
        r.raise_for_status()
        routes = r.json().get("routes", [])
        route = routes[0] if routes else {}
        summary = route.get("summary")
        # 경로 없음(result_code≠0 등)이면 summary가 없다 → 직선 폴백
        if summary:
            path: list[LatLng] = []
            highway_m = 0.0  # 고속도로 주행거리
            local_m = 0.0  # 일반도로/국도
            jam_m = 0.0  # 정체(traffic_state 4)
            delay_m = 0.0  # 지체(traffic_state 3)
            # 소비 예측용 구간: (거리km, 실제속도km/h, 도로등급)
            segments: list[tuple[float, float, str]] = []
            # 지도 표시용 정체/지체 연속 스트레치
            congestion: list[dict] = []
            cur: dict | None = None  # 현재 스트레치 누적

            # 진행 중인 정체/지체 스트레치를 확정해 congestion에 담는다.
            # 같은 level이 연속되는 동안 누적하다가, level이 바뀌거나 원활 구간을
            # 만나면 flush → 지도에 잘게 쪼개진 선분 대신 연속 구간 하나로 그려진다.
            # 평균속도는 거리가중(Σ속도×거리 ÷ Σ거리), 고속도로 여부는 거리 과반 기준.
            def _flush() -> None:
                nonlocal cur
                if cur and cur["dist_m"] > 0:
                    congestion.append({
                        "level": cur["level"],
                        "path": cur["path"],
                        "distance_km": round(cur["dist_m"] / 1000.0, 1),
                        "speed_kmh": round(cur["spd_sum"] / cur["dist_m"], 1),
                        "is_highway": cur["hw_m"] * 2 >= cur["dist_m"],
                    })
                cur = None

            # 카카오 응답 구조: routes[].sections[].roads[]
            #   road.vertexes = [lng, lat, lng, lat, ...] 평탄화 배열 (경도가 먼저)
            #   road.distance = m, road.duration = 초, road.traffic_speed = km/h
            #   road.traffic_state = 0~4 (4=정체, 3=지체, 그 외/없음=원활·정보없음)
            # 도로 단위로 순회하며 ①폴리라인 ②소비예측용 세그먼트 ③정체 스트레치를
            # 한 번에 만든다(같은 배열을 세 번 도는 것을 피함).
            for section in route.get("sections", []):
                for road in section.get("roads", []):
                    verts = road["vertexes"]
                    coords = [
                        LatLng(lat=verts[i + 1], lng=verts[i])
                        for i in range(0, len(verts), 2)
                    ]
                    path.extend(coords)
                    d = road.get("distance") or 0
                    if d <= 0:
                        continue
                    # 구간 실제속도: traffic_speed(교통반영) 우선, 없으면 거리/시간
                    spd = road.get("traffic_speed") or 0
                    dur = road.get("duration") or 0
                    if not spd and dur > 0:
                        spd = (d / 1000.0) / (dur / 3600.0)
                    spd = float(spd) or 60.0
                    rc = _road_class(road.get("name"), spd)
                    hw = rc != "local"
                    segments.append((d / 1000.0, spd, rc))
                    if hw:
                        highway_m += d
                    else:
                        local_m += d
                    # 정체(4)/지체(3) 분류 + 연속 구간 그룹핑
                    ts = road.get("traffic_state")
                    level = "jam" if ts == 4 else "delay" if ts == 3 else None
                    if level == "jam":
                        jam_m += d
                    elif level == "delay":
                        delay_m += d
                    if level is None:
                        _flush()
                    else:
                        if cur is None or cur["level"] != level:
                            _flush()
                            cur = {"level": level, "path": [], "dist_m": 0.0,
                                   "spd_sum": 0.0, "hw_m": 0.0}
                        cur["path"].extend(coords)
                        cur["dist_m"] += d
                        cur["spd_sum"] += spd * d
                        if hw:
                            cur["hw_m"] += d
            _flush()
            return {
                "distance_km": round(summary["distance"] / 1000.0, 1),
                "duration_min": round(summary["duration"] / 60),
                "path": path or _interpolate(origin, dest),
                "highway_km": round(highway_m / 1000.0, 1),
                "local_km": round(local_m / 1000.0, 1),
                "segments": segments,
                "congestion": congestion,
                "jam_km": round(jam_m / 1000.0, 1),
                "delay_km": round(delay_m / 1000.0, 1),
                "source": "kakao",
            }

    # 실데이터 모드에서는 실제 도로 경로 실패 시 오류 — 직선 추정 경로가 실제
    # 경로처럼 쓰여 엉뚱한 충전소가 추천되는 것을 막는다.
    if not settings.mock_enabled:
        raise RouteUnavailable(f"{origin} -> {dest}")

    # 폴백(mock_enabled): 직선거리 × 1.3(도로 우회 계수) — source=mock로 표시
    from .charging import _haversine_km

    straight = _haversine_km(origin, dest)
    dist = straight * 1.3
    return {
        "distance_km": round(dist, 1),
        "duration_min": round(dist / 80.0 * 60),  # 평균 80km/h 가정
        "path": _interpolate(origin, dest),
        "highway_km": 0.0,  # 추정 경로는 도로유형 미상 → 전부 일반도로로 간주
        "local_km": round(dist, 1),
        "segments": [(round(dist, 1), 60.0, False)],
        "congestion": [],  # 추정 경로는 교통정보 없음
        "jam_km": 0.0,
        "delay_km": 0.0,
        "source": "mock",
    }
