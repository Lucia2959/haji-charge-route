"""외부기관 연계용 공용 HTTP 클라이언트 + 사용량 초과 예외.

연결 안정성:
  - 매 호출 새 클라이언트를 만드는 대신 keep-alive 커넥션 풀을 재사용해 TLS
    핸드셰이크 부하를 줄이고, 전역 동시 연결 수를 제한(httpx.Limits)한다.
  - 앱 종료 시 aclose()로 정리(main.py lifespan).

QuotaExceeded:
  - 무료 사용량 초과 / 유료 과금 발생 신호(EV resultCode 22, Kakao 지속 429)를
    network 오류·내부 호출제한과 '구분'해 상위로 전달한다. 라우터는 이를 HTTP 402로
    변환해 화면에 "사용량이 초과하였습니다"를 표시한다.
"""

from __future__ import annotations

import httpx


class QuotaExceeded(Exception):
    """외부 API 무료 사용량 초과 / 과금 발생 (network·내부 호출제한과 구분)."""

    def __init__(self, provider: str = "") -> None:
        super().__init__(provider)
        self.provider = provider


# 전역 동시 연결 상한(앱의 Kakao 6 + EV 4 동시성 + 여유). keepalive로 연결 재사용.
_limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    """공유 AsyncClient(지연 생성). 호출부는 필요 시 timeout=을 개별 지정."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(20.0), limits=_limits)
    return _client


async def aclose() -> None:
    """앱 종료 시 커넥션 풀 정리."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
