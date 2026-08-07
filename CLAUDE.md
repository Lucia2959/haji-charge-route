# CLAUDE.md

BYD 돌핀 EV 충전 경로 안내 웹앱. **실주행에 쓰는 앱**이므로 계산값이 틀리면 사용자가
길에서 방전된다. 추정·목(mock)으로 조용히 폴백하지 말 것.

## 스택

- `frontend/` — Next.js 15 App Router, React 19, TypeScript, Tailwind 4, 카카오맵 → **Vercel**
- `backend/` — FastAPI, Python 3.12, httpx → **Render 무료(싱가포르, 512MB, 슬립 있음)**
- DB — Neon/Supabase 무료 Postgres (혼잡 예측 전용. 없으면 그 기능만 꺼지고 경로 계획은 동작)
- 외부 API — Kakao(로컬/경로), 공공데이터포털 충전소, open-meteo

프런트는 백엔드 REST만 호출한다. API 키·CORS는 전부 백엔드가 처리한다.

## 문서 — 코드 고치기 전에 볼 것

| 문서 | 언제 |
|---|---|
| `docs/01-앱기능설계서.md` | 계산 알고리즘·업무규칙을 건드릴 때 |
| `docs/02-화면기능정의서.md` | 화면 UI·이벤트·검증을 바꿀 때 |
| `docs/03-시스템아키텍처.md` | 모듈·캐시 구조를 바꿀 때 |
| `docs/04-운영이슈.md` | **성능·보안 이슈가 보고될 때 반드시 먼저.** 대부분 이미 원인·실측·조치가 적혀 있다 |
| `docs/05-품질처리내역.md` | "이거 왜 안 고쳤나" 싶을 때 (미적용 사유 포함) |
| `docs/06`, `docs/07` | 성수기 충전 혼잡 예측 기능 |
| `DEPLOY.md` / `TODO.md` | 배포 절차 / 잔여 작업 |

## 절대 건드리지 말 것

전체 목록은 **`docs/04-운영이슈.md` §5**. 자주 무심코 깨지는 것들:

- `_FETCH_CONCURRENCY = 4` (`ev_stations.py`) — 8로 올리면 공공 API가 즉시 차단. 실측 확인됨. 병렬화로 속도를 못 줄인다
- `_PLAN_CONCURRENCY = 2` (`routers/route.py`) — 올리면 512MB에서 OOM
- `--workers 1`, `--proxy-headers --forwarded-allow-ips="*"` (`render.yaml`) — 캐시·rate limit이 인메모리라 워커가 늘면 깨지고, 프록시 헤더가 없으면 rate limit이 전체 합산이 되어 자가 DoS
- `MOCK_ENABLED=false` — `true`면 가짜 경로가 진짜처럼 표시된다
- `normalize_zscode()` (`ev_stations.py:_districts_for_path`) — 빼면 성남·용인·수원·고양 등 일반구가 있는 시의 충전소가 통째로 누락된다
- `_KEEP_FIELDS` 투영 (`ev_stations.py:_project_row`) — 응답에 필드를 새로 쓰려면 **여기 먼저** 추가. 안 하면 조용히 빈 값이 된다
- `COLLECT_TOKEN ≠ API_TOKEN` — `API_TOKEN`은 프런트 번들에 노출된다
- `_ALT_MIN_POWER_RATIO = 0.5` (`routers/route.py`) — 낮추면 급속 계획에 완속이 대체로 붙어 화면 충전시간이 거짓이 된다 (100kW 28분 vs 7kW 238분)
- T맵 딥링크의 **X=경도 / Y=위도** (`lib/tmap.ts`) — 바꿔도 앱은 열리고 엉뚱한 곳으로 안내한다. `node src/lib/tmap.test.mjs`가 고정
- 즐겨찾기 칩의 `w-full` (`main/page.tsx:Shortcut`) — 빼면 저장된 칩만 줄어들고 배지가 칩 밖으로 나간다

## 알려진 특성 (버그 아님)

- **콜드 캐시 첫 계산 40~60초** — 카탈로그 fetch 4.5s + Render 콜드스타트. keep-alive 크론(`/health`, 10분)이 살아 있는지부터 확인. 프런트 타임아웃은 120초로 의도적으로 늘려둔 것
- **동시 사용자가 늘면 비례해 느려짐** — 세마포어가 모듈 전역. 쿼터 보호를 위한 의도된 트레이드오프
- 지도 폴리라인은 표시용으로 1200점만 솎아낸다. **계산에는 원본 `path`를 쓴다**

## 실행

```bash
# 백엔드 (포트 8000)
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 프런트 (포트 3000)
cd frontend && npm run dev
```

Windows에서 파이썬 출력이 깨지면 `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`을 앞에 붙인다.
서버가 안 죽었을 때는 `netstat -ano`로 8000/3000 PID를 찾아 `taskkill //F //PID <pid>`.

## 변경 후 필수 검증

```bash
cd backend
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe test_planning.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe test_consumption.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe test_external_stability.py
cd ../frontend && npx tsc --noEmit
node src/lib/tmap.test.mjs             # T맵 딥링크 좌표 순서(X=경도)
git status --short | grep -E "\.env"   # 아무것도 안 나와야 정상
```

## 관례

- UI 아이콘은 `.claude/skills/irasutoya-icons` 규칙을 따른다 (이라스토야 우선, 새 아이콘 라이브러리 추가 금지)
- 문서는 한국어로 쓴다
- 라이브러리 문법·설정을 다룰 때는 기억에 의존하지 말고 context7로 현재 문서를 확인한다 (Next 15.5 / React 19 / Tailwind 4 / FastAPI)
