"""DB 접속·스키마 점검. 실행: python check_db.py

DATABASE_URL을 .env(또는 환경변수)에서 읽어 연결만 확인한다.
**비밀번호는 어디에도 출력하지 않는다** — 호스트·포트만 표시한다.

수집 크론을 걸기 전에 이걸로 먼저 확인하면, 크론이 조용히 실패하는 상황을 피할 수 있다.
"""

import asyncio
import re
import sys
from urllib.parse import urlparse

from app import db
from app.config import settings


async def main() -> int:
    if not settings.use_db:
        print("✗ DATABASE_URL이 비어 있습니다 (backend/.env 또는 환경변수).")
        print("  → 혼잡 예측만 꺼지고 앱의 나머지는 정상 동작합니다.")
        return 1

    # Supabase 대시보드의 복사 버튼은 비밀번호 자리에 [YOUR-PASSWORD]를 넣어준다.
    # 그대로 붙여넣으면 대괄호 때문에 urlparse가 IPv6 주소로 오인해 터진다 —
    # 원인이 안 보이는 예외라 여기서 먼저 잡아 알려준다.
    if re.search(r":\[[^\]/@]*\]@", settings.database_url):
        print("✗ DATABASE_URL에 비밀번호 자리표시자가 그대로 있습니다.")
        print("  '[YOUR-PASSWORD]' 부분을 실제 DB 비밀번호로 바꾸세요(대괄호도 지웁니다).")
        print("  비밀번호를 모르면 Supabase Dashboard > Settings > Database >")
        print("  Database password > Reset database password 에서 새로 발급합니다.")
        return 1

    try:
        u = urlparse(settings.database_url)
        port = u.port or 5432
        hostname = u.hostname
    except ValueError:
        print("✗ DATABASE_URL 형식이 올바르지 않습니다.")
        print("  기대 형식: postgresql://<사용자>:<비밀번호>@<호스트>:5432/postgres")
        return 1
    if not hostname:
        print("✗ DATABASE_URL에서 호스트를 찾지 못했습니다. 문자열을 다시 복사하세요.")
        return 1
    print(f"대상: {hostname}:{port}  DB={(u.path or '/').lstrip('/') or '(기본)'}")

    # Supabase 접속 방식 진단 — 여기서 막히는 경우가 대부분이다.
    host = hostname
    if host.startswith("db.") and "supabase" in host:
        print("⚠ 직접 연결(db.*.supabase.co)은 IPv6 전용이라 Render 무료에서 붙지 않습니다.")
        print("  → Dashboard > Connect > **Session pooler** 문자열을 쓰세요.")
    elif "pooler.supabase.com" in host:
        mode = "트랜잭션" if port == 6543 else "세션"
        print(f"  Supavisor {mode} 풀러 (포트 {port}) — 둘 다 지원합니다.")

    await db.connect()
    p = db.pool()
    if p is None:
        print("✗ 연결 실패. 위 로그의 예외 종류를 확인하세요.")
        print("  자주 나오는 원인: 비밀번호 불일치 / 직접연결(IPv6) 사용 / 사용자명 형식")
        print("  Supabase 풀러 사용자명은 'postgres.<프로젝트ref>' 형식입니다.")
        return 1

    async with p.acquire() as conn:
        ver = await conn.fetchval("SELECT version()")
        tables = [
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename IN ('session','occupancy_stat') ORDER BY 1"
            )
        ]
        sessions = await conn.fetchval("SELECT COUNT(*) FROM session")
        stations = await conn.fetchval("SELECT COUNT(DISTINCT station_id) FROM session")
        cells = await conn.fetchval("SELECT COUNT(*) FROM occupancy_stat")
        ready = await conn.fetchval(
            "SELECT COUNT(*) FROM occupancy_stat WHERE n_days >= $1", 8
        )
        oldest = await conn.fetchval("SELECT MIN(started_at) FROM session")

    print(f"✓ 연결 성공 — {ver.split(',')[0]}")
    print(f"  테이블: {', '.join(tables) if tables else '(없음 — 스키마 적용 실패)'}")
    print(f"  세션 {sessions:,}건 / 충전소 {stations:,}곳 / 최초관측 {oldest or '-'}")
    print(f"  집계 셀 {cells:,}개 (예측에 실제로 쓰이는 셀 {ready:,}개)")

    if sessions == 0:
        print("\n다음 단계: /internal/collect 를 한 번 호출해 수집이 되는지 확인하세요.")
    elif ready == 0:
        print("\n아직 관측일이 부족합니다 — 평일 약 2주, 주말 약 4주 뒤부터 예측이 나옵니다.")
        print("(그 전까지는 '데이터 부족'으로 두고 추측값을 내지 않습니다.)")

    await db.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
