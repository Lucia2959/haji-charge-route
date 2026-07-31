"""외부기관 연계 안정성 자체검증 — 공유 클라이언트에 MockTransport 주입(네트워크 없이).
실행: python test_external_stability.py

검증 포인트:
  - 재시도/백오프: 일시 429·5xx·전송오류를 흡수
  - 사용량 초과 구분: Kakao 지속 429 / EV resultCode 22(본문) → QuotaExceeded
  - 비재시도성(4xx)·지속 전송오류는 각각 즉시 반환 / raise
  - 동시성: in-flight 공유가 취소를 전파하지 않는가 / 요청제한 버킷 매칭
"""
import asyncio

import httpx

import app.http as http
from app.config import settings
from app.http import QuotaExceeded, RateLimited
from app.ratelimit import _DEFAULT_LIMIT, _bucket
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

# 7) EV 지속 429(근거 없음) → RateLimited
def h7(req):
    return httpx.Response(429)
try:
    run(lambda: ev_stations._get_with_retry({"a": 1}), h7)
    raise AssertionError("근거 없는 지속 429는 RateLimited 여야 함")
except RateLimited:
    pass

# 8) EV 429 + 본문 "API token quota exceeded" → QuotaExceeded (실제 관측된 형태)
#    상태코드만 보면 일시제한으로 오판해 "잠시 후 재시도"를 안내하게 된다.
n8 = {"c": 0}
def h8(req):
    n8["c"] += 1
    return httpx.Response(429, text="API token quota exceeded\n")
try:
    run(lambda: ev_stations._get_with_retry({"a": 1}), h8)
    raise AssertionError("쿼터 소진 본문이면 QuotaExceeded 여야 함")
except QuotaExceeded:
    assert n8["c"] == 1, f"쿼터 소진은 재시도 없이 즉시 중단해야 함 (시도 {n8['c']}회)"


# ── 동시성 ────────────────────────────────────────────────────────────────
# 9) in-flight 공유: '주인' 요청이 취소돼도 편승자는 살아야 한다.
#    shield 없이 await 하면 취소가 공유 Task로 전파돼 무관한 요청까지 죽는다
#    (워밍업이 주인인 상태에서 사용자가 화면을 벗어나면 계산 요청이 함께 실패).
settings.ev_station_api_key = "TEST"
ONE = (
    "<response><body><items><item><statId>S1</statId><statNm>충전소</statNm>"
    "<chgerId>1</chgerId><chgerType>04</chgerType><lat>36.5</lat><lng>127.5</lng>"
    "<stat>2</stat><output>100</output><limitYn>N</limitYn></item></items>"
    "<totalCount>1</totalCount></body></response>"
)


async def h9(req):
    await asyncio.sleep(0.3)          # 조회가 진행 중인 동안 취소를 끼워 넣기 위한 지연
    return httpx.Response(200, text=ONE)


async def _cancel_owner_keep_rider():
    ev_stations._catalog_cache.clear()
    ev_stations._catalog_inflight.clear()
    ev_stations._status_cache.clear()
    owner = asyncio.create_task(ev_stations._get_catalog("11", "11110"))
    await asyncio.sleep(0.05)         # 주인이 공유 Task를 만들 때까지 양보
    rider = asyncio.create_task(ev_stations._get_catalog("11", "11110"))
    await asyncio.sleep(0.05)         # 편승자가 shield await 에 진입
    owner.cancel()                    # 클라이언트 연결 끊김 / 프런트 타임아웃
    return (
        await asyncio.gather(owner, return_exceptions=True),
        await asyncio.gather(rider, return_exceptions=True),
    )


(o_res,), (r_res,) = run(_cancel_owner_keep_rider, h9)
assert isinstance(o_res, asyncio.CancelledError), f"주인은 취소돼야 함: {o_res!r}"
assert not isinstance(r_res, BaseException), f"편승자는 살아야 함: {r_res!r}"
assert len(r_res) == 1 and r_res[0].id == "S1", f"편승자가 결과를 받아야 함: {r_res!r}"
# 주인이 취소되며 in-flight 항목이 새어 남지 않아야(다음 요청이 캐시를 쓰도록)
assert not ev_stations._catalog_inflight, "in-flight 항목이 정리되지 않음"
assert "11:11110" in ev_stations._catalog_cache, "취소와 무관하게 캐시는 채워져야 함"

# 10) 요청제한 버킷: warmup 이 기본값(120)으로 새지 않아야 한다.
#     _bucket 은 startswith 매칭이라 prefix를 빠뜨리면 조용히 기본값을 받는다.
assert _bucket("/api/route/plan")[1] == 20
w_prefix, w_limit = _bucket("/api/route/warmup")
assert w_prefix == "/api/route/warmup", f"warmup 전용 버킷이 없음: {w_prefix}"
assert w_limit < _DEFAULT_LIMIT, f"warmup 이 기본값으로 샘: {w_limit}"

print("OK — 외부 연계 안정성: 재시도/백오프, 쿼터소진(코드22)과 일시제한(429) 구분, 4xx 즉시반환, 전송오류 raise")
print(f"     + 동시성: in-flight 취소 비전파(주인 취소·편승자 생존), warmup 버킷 {w_limit}/분")
