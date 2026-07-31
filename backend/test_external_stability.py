"""외부기관 연계 안정성 자체검증 — 공유 클라이언트에 MockTransport 주입(네트워크 없이).
실행: python test_external_stability.py

검증 포인트:
  - 재시도/백오프: 일시 429·5xx·전송오류를 흡수
  - 사용량 초과 구분: Kakao 지속 429 / EV resultCode 22(본문) → QuotaExceeded
  - 비재시도성(4xx)·지속 전송오류는 각각 즉시 반환 / raise
"""
import asyncio

import httpx

import app.http as http
from app.http import QuotaExceeded, RateLimited
from app.services import ev_stations
from app.services.kakao import _MAX_RETRY as K_RETRY, _get_retry


def run(factory, handler):
    async def go():
        http._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await factory()
        finally:
            await http.aclose()
    return asyncio.run(go())


# 1) Kakao 429,429,200 → 재시도 후 200
n1 = {"c": 0}
def h1(req):
    n1["c"] += 1
    return httpx.Response(200 if n1["c"] >= 3 else 429)
assert run(lambda: _get_retry("https://x/"), h1).status_code == 200 and n1["c"] == 3

# 2) Kakao 지속 429 → RateLimited(단시간 과다호출), _MAX_RETRY회 시도
#    429는 쿼터 '소진'이 아니므로 QuotaExceeded로 승격하면 안 된다(오안내).
n2 = {"c": 0}
def h2(req):
    n2["c"] += 1
    return httpx.Response(429)
try:
    run(lambda: _get_retry("https://x/"), h2)
    raise AssertionError("지속 429는 RateLimited 여야 함")
except RateLimited:
    assert n2["c"] == K_RETRY

# 3) Kakao 5xx → 재시도 후 200
n3 = {"c": 0}
def h3(req):
    n3["c"] += 1
    return httpx.Response(200 if n3["c"] >= 2 else 503)
assert run(lambda: _get_retry("https://x/"), h3).status_code == 200

# 4) 4xx는 비재시도 → 즉시 반환(호출부 raise_for_status가 처리)
n4 = {"c": 0}
def h4(req):
    n4["c"] += 1
    return httpx.Response(400)
assert run(lambda: _get_retry("https://x/"), h4).status_code == 400 and n4["c"] == 1

# 5) 전송오류 지속 → raise(network 오류, 사용량초과 아님)
n5 = {"c": 0}
def h5(req):
    n5["c"] += 1
    raise httpx.ConnectError("boom")
try:
    run(lambda: _get_retry("https://x/"), h5)
    raise AssertionError("전송오류 지속 시 raise 해야 함")
except httpx.ConnectError:
    assert n5["c"] == K_RETRY

# 6) EV 본문 호출초과 마커(코드22) → QuotaExceeded (HTTP 200이어도)
LIMIT = (
    "<OpenAPI_ServiceResponse><cmmMsgHeader>"
    "<returnReasonCode>22</returnReasonCode>"
    "<returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>"
    "</cmmMsgHeader></OpenAPI_ServiceResponse>"
)
def h6(req):
    return httpx.Response(200, text=LIMIT)
try:
    run(lambda: ev_stations._fetch_rows("11", "11110"), h6)
    raise AssertionError("EV 호출초과 본문은 QuotaExceeded 여야 함")
except QuotaExceeded:
    pass

# 7) EV 지속 429 → RateLimited (본문 코드22만 QuotaExceeded)
def h7(req):
    return httpx.Response(429)
try:
    run(lambda: ev_stations._get_with_retry({"a": 1}), h7)
    raise AssertionError("EV 지속 429는 RateLimited 여야 함")
except RateLimited:
    pass

print("OK — 외부 연계 안정성: 재시도/백오프, 쿼터소진(코드22)과 일시제한(429) 구분, 4xx 즉시반환, 전송오류 raise")
