"""Postgres 커넥션 풀 (asyncpg 직접 사용, ORM 없음).

**DB는 선택 사항이다.** `DATABASE_URL`이 비어 있으면 풀을 만들지 않고 `pool()`이
None을 반환한다 → 혼잡 예측 기능만 조용히 꺼지고 계획·지도·충전소 조회는 그대로
동작한다. 로컬 개발과 DB 미프로비저닝 상태에서도 앱이 떠야 하기 때문이다.

asyncpg import도 지연시킨다. 파이썬 최신 버전에는 아직 휠이 없을 수 있는데,
DB를 안 쓰는 환경에서 그것 때문에 앱 전체가 못 뜨면 곤란하다.

ORM/마이그레이션 도구를 쓰지 않는 이유: 테이블 2개·쿼리 4개 규모라
SQLAlchemy+Alembic은 유지보수 부담만 늘린다. 스키마는 schema.sql에
`IF NOT EXISTS`로 적고 기동 시 1회 실행한다. docs/07 §3-4.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

_SCHEMA = Path(__file__).with_name("schema.sql")

# 풀 크기 상한. 무료 Postgres(Neon/Supabase)는 동시 접속 한도가 낮고,
# 앱은 --workers 1 단일 프로세스라 이 이상이 필요 없다.
_POOL_MIN = 1
_POOL_MAX = 2
# DB가 느려도 계획 응답을 붙잡지 않는다 — 예측은 있으면 좋은 것이지 필수가 아니다.
_CONNECT_TIMEOUT = 10.0

# 준비된 구문(prepared statement) 캐시를 끈다.
#
# Supabase/Neon의 **트랜잭션 풀러**(Supavisor 6543 / PgBouncer transaction 모드)는
# 커넥션을 문장 단위로 돌려쓰기 때문에 prepared statement를 지원하지 않는다.
# asyncpg는 기본으로 이걸 쓰므로, 끄지 않으면 트랜잭션 모드 접속에서
# `prepared statement "__asyncpg_stmt_x__" does not exist` 로 깨진다.
#
# 세션 모드(5432)에서는 켜도 되지만, 어느 쪽 문자열이 들어올지 배포 시점에
# 알 수 없다. 우리 쿼리는 계획 1건당 1회 + 5분당 배치 INSERT 1회뿐이라
# 캐시를 껐을 때의 손해가 사실상 없다 → 항상 꺼서 양쪽 다 동작하게 한다.
_STATEMENT_CACHE = 0


def _safe_host(dsn: str) -> str:
    """로그용 호스트 표기. **비밀번호가 로그에 남지 않도록** 호스트만 잘라낸다."""
    try:
        from urllib.parse import urlparse

        u = urlparse(dsn)
        return f"{u.hostname}:{u.port or 5432}"
    except Exception:  # noqa: BLE001
        return "(파싱 불가)"

_pool: Any = None


def pool() -> Any:
    """활성 커넥션 풀 또는 None(DB 미설정·연결 실패)."""
    return _pool


async def connect() -> None:
    """풀 생성 + 스키마 적용. 실패해도 예외를 밖으로 내지 않는다.

    DB 연결 실패로 앱 자체가 못 뜨면, 혼잡 예측이라는 부가 기능 때문에
    핵심 기능(경로 계획)까지 죽는 셈이 된다. 로그만 남기고 계속 간다.
    """
    global _pool
    if not settings.use_db:
        return
    try:
        import asyncpg  # 지연 import — DB를 안 쓰면 설치조차 필요 없다
    except ImportError:
        log.warning("DATABASE_URL은 설정됐지만 asyncpg가 없다 — 혼잡 예측 비활성")
        return
    try:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=_POOL_MIN,
            max_size=_POOL_MAX,
            timeout=_CONNECT_TIMEOUT,
            command_timeout=30.0,
            statement_cache_size=_STATEMENT_CACHE,
        )
        async with _pool.acquire() as conn:
            await conn.execute(_SCHEMA.read_text(encoding="utf-8"))
        log.info(
            "DB 연결 완료 %s (풀 %d~%d)",
            _safe_host(settings.database_url), _POOL_MIN, _POOL_MAX,
        )
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 앱은 계속 떠야 한다
        # 예외 메시지에 접속 문자열이 통째로 실릴 수 있어 호스트만 따로 찍는다.
        log.warning(
            "DB 연결 실패 %s — 혼잡 예측 비활성: %s",
            _safe_host(settings.database_url), type(exc).__name__,
        )
        _pool = None


async def aclose() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
