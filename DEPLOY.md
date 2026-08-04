# 배포 가이드 — 아이폰에서 웹앱으로 쓰기

프런트 **Vercel(무료)** + 백엔드 **Render(무료)** 구성이다.

## 왜 이 조합인가

| 플랫폼 | 판정 |
|---|---|
| **Vercel — 프런트** | Next.js 네이티브, HTTPS 자동, 콜드스타트 없음. Hobby는 **비상업 전용**이라 개인 앱에 적합 |
| **Render — 백엔드** | 무료 512MB, HTTPS 자동, **싱가포르 리전**(한국에서 가장 가까운 무료) |
| ~~Fly.io~~ | 2026년 무료 티어 종료(신규는 체험판만) |
| ~~Railway~~ | $5 크레딧 소진 후 유료 |
| ~~Vercel에 백엔드~~ | **함수 10초 타임아웃** — 경로계산이 3~14초라 불가. 게다가 서버리스는 인메모리 캐시가 매번 날아가 외부 API 쿼터를 태운다 |

이 백엔드는 **인메모리 캐시(카탈로그 6시간)와 rate limit**을 쓰므로 **상시 단일 인스턴스**여야 한다. 그래서 서버리스·다중 인스턴스는 부적합하다.

### 속도 — 왜 첫 계산이 느리고, 어떻게 빠르게 하나

400km 경로 1회 계산의 시간 분해(실측):

| 단계 | 시간 | 비중 |
|---|---|---|
| 충전소 카탈로그 fetch (24개 시군구) | 4.5s | **57%** |
| 카카오 경로 조회 | 2.3s | 29% |
| 근접 필터·투영·DP 등 CPU 전부 | 0.4s | 5% |

**병렬화로는 못 줄인다.** 동시 호출을 4 → 8로 올려 측정했더니 공공데이터 API가
곧바로 호출초과로 차단했다(4는 정상). `_FETCH_CONCURRENCY`는 건드리지 말 것.

그래서 유일하게 효과적인 수단은 **카탈로그 캐시를 살려두는 것**이다.

- 캐시가 살아있으면 위 4.5초가 통째로 사라져 **계획이 3초 안팎**으로 끝난다.
- 캐시 수명은 24시간(`_CATALOG_TTL`)이다. 담는 게 위치·이름·출력 같은 정적
  메타데이터라 길게 잡아도 안전하다(실시간 사용가능 여부는 별도 20초 캐시).
- **문제는 Render 무료가 15분 무요청 시 잠들면서 메모리 캐시를 통째로 날린다는 것.**
  깨어날 때 30~60초 + 카탈로그 재빌드가 겹쳐 첫 사용이 1분을 넘길 수 있다.

**해결: keep-alive 크론 (무료)**

`https://<백엔드>.onrender.com/health` 를 **10분마다** 호출하도록 걸어둔다.

1. [cron-job.org](https://cron-job.org) 무료 가입 → Create cronjob
2. URL에 위 `/health` 주소, 실행 주기 **매 10분**
3. 저장 (인증 불필요 — `/health`는 토큰 검사 대상이 아니다)

> **혼잡 예측(docs/07)을 켰다면 이 크론은 필요 없다.** 아래 6장의 수집 크론이
> 5분마다 `/internal/collect`를 부르므로 keep-alive를 겸한다. 둘 다 걸면
> 호출만 두 배가 된다 → **수집 크론으로 대체하고 `/health` 크론은 삭제할 것.**

이렇게 하면 서비스가 잠들지 않아 **콜드스타트도, 카탈로그 재빌드도 없어진다.**
Render 무료는 월 750 인스턴스시간이고 한 달은 ~730시간이라 **서비스 1개는 상시
가동해도 쿼터 안에 든다.**

남는 2.3초(카카오 경로 조회)는 외부 API라 단축할 수 없다.

---

## 1. 사전 준비

1. GitHub 저장소 생성 후 푸시
   ```bash
   git init && git add -A && git commit -m "init"
   ```
   **푸시 전 반드시 확인** — `.env`, `.env.local`이 커밋에서 빠졌는지:
   ```bash
   git status --short | grep -E "\.env"   # 아무것도 안 나와야 정상
   ```

2. 발급받을 것
   - Kakao REST API 키 / JavaScript 키 (Kakao Developers)
   - 공공데이터포털 전기차 충전소 정보 서비스 키 (**디코딩 키**)
   - 공유 시크릿 1개 직접 생성: `openssl rand -hex 16`

---

## 2. 백엔드 — Render

1. render.com → New → **Blueprint** → 저장소 선택 (루트의 `render.yaml` 자동 인식)
2. 환경변수 입력 (대시보드에서, 파일에 넣지 말 것)

   | 키 | 값 |
   |---|---|
   | `KAKAO_REST_API_KEY` | 카카오 REST 키 |
   | `EV_STATION_API_KEY` | 공공데이터 디코딩 키 |
   | `API_TOKEN` | 위에서 만든 시크릿 |
   | `FRONTEND_ORIGIN` | (3단계 후) `https://<프로젝트>.vercel.app` |
   | `APP_ENV` | `production` |
   | `MOCK_ENABLED` | `false` |

3. 배포 후 확인
   ```bash
   curl https://<백엔드>.onrender.com/health     # {"status":"ok"} 만 나오면 정상
   ```

> `render.yaml`의 `--proxy-headers --forwarded-allow-ips="*"` 는 필수다. 없으면 모든 사용자가 프록시 IP 하나로 묶여 rate limit이 "전체 합산 20회/분"이 된다.
> `--workers 1` 도 필수다. 워커가 늘면 인메모리 캐시가 쪼개지고 제한이 워커 수만큼 곱해진다.

---

## 3. 프런트 — Vercel

1. vercel.com → Add New → Project → 저장소 선택
2. **Root Directory: `frontend`** 로 지정
3. 환경변수 (Production)

   | 키 | 값 |
   |---|---|
   | `NEXT_PUBLIC_API_BASE` | `https://<백엔드>.onrender.com` ← **반드시 https, 끝 슬래시 없이** |
   | `NEXT_PUBLIC_KAKAO_JS_KEY` | 카카오 JS 키 |
   | `NEXT_PUBLIC_API_TOKEN` | 2단계의 `API_TOKEN`과 **같은 값** |

4. 배포 후 Render의 `FRONTEND_ORIGIN`을 실제 Vercel 주소로 수정 → 재배포 (CORS)

> `NEXT_PUBLIC_*`은 **빌드 시점에 번들로 굳는다.** 값을 바꾸면 반드시 재배포해야 반영된다.

---

## 4. 카카오 도메인 등록 (안 하면 지도가 안 뜸)

> 2026-07-21 콘솔 개편으로 도메인 설정이 **앱 키 하위로 이동**했다. 예전의
> "플랫폼 → Web → 사이트 도메인" 경로는 더 이상 없다.

경로: **앱 설정 → 앱 → 플랫폼 키 → `JavaScript 키` 선택 → JavaScript SDK 도메인**

여기에 `https://haji-charge-route.vercel.app` 를 추가한다.

주의:
- **REST API 키가 아니라 JavaScript 키**를 열어야 한다. REST 키 화면에도 비슷한
  입력칸(호출 허용 IP, 카카오 로그인 리다이렉트 URI)이 있어 헷갈리기 쉽다.
- REST 키의 **"호출 허용 IP 주소"는 비워 둔다.** Render 무료 플랜은 아웃바운드 IP가
  고정되지 않아, 등록하면 어느 순간 경로 조회가 통째로 막힌다.
- 카카오맵이 별도 제품으로 분리되어, **제품 설정 → 카카오맵**에서 사용 설정·무료
  쿼터 상태를 함께 확인한다.

---

## 5. 아이폰에 설치

1. Safari로 `https://<프로젝트>.vercel.app` 접속
2. 공유 버튼 → **홈 화면에 추가**
3. 홈 화면 아이콘으로 실행하면 주소창 없는 전체화면(standalone)으로 뜬다

### 첫 실행 시 즐겨찾기 등록
집·회사 주소는 **앱에서 직접 등록**한다. `＋ 즐겨찾기` 버튼 → 장소 검색 → 선택.
주소는 **그 기기의 localStorage에만** 저장되고 서버·번들에는 남지 않는다.
(예전처럼 환경변수에 넣으면 빌드 결과물에 주소가 박혀 URL만 알면 누구나 읽을 수 있다.)

---

## 6. 성수기 혼잡 예측 켜기 (선택)

이 절을 건너뛰어도 앱은 그대로 동작한다. `DATABASE_URL`이 비어 있으면 예측 기능만
꺼지고 경로 계획·지도·충전소 조회는 영향이 없다. 설계 근거는 [docs/07](docs/07-확장설계안-성수기혼잡.md).

### 6-1. Postgres 준비

[Neon](https://neon.tech) 또는 [Supabase](https://supabase.com) 무료 프로젝트를 만들고
접속 문자열을 복사한다. 둘 다 0.5GB·만료 없음이고, 5분마다 쓰기가 들어가므로
유휴 절전에 걸리지 않는다.

> **SQLite를 쓰면 안 된다.** Render 무료 웹 서비스는 파일시스템이 휘발성이라
> 재배포·재시작마다 초기화된다. 몇 주 모은 데이터가 배포 한 번에 사라지면
> 콜드스타트가 영원히 끝나지 않는다.
>
> **Render 무료 Postgres도 권하지 않는다** — 무료 인스턴스에 만료 정책이 있어
> 만료되면 데이터가 사라진다.

**Supabase를 쓸 때 — 반드시 Session pooler 문자열을 쓸 것**

Dashboard 우측 상단 **Connect** 버튼에서 세 가지 문자열이 나온다. 고를 것은 하나뿐이다.

| 방식 | 호스트 | 판정 |
|---|---|---|
| Direct connection | `db.<ref>.supabase.co:5432` | ❌ **IPv6 전용.** DNS에 A 레코드가 없어 Render에서 붙지 않는다(실측: 조회 실패) |
| **Session pooler** | `aws-N-<리전>.pooler.supabase.com:5432` | ✅ **이걸 쓴다.** IPv4 |
| Transaction pooler | `aws-N-<리전>.pooler.supabase.com:6543` | ⚠ 되지만 굳이 |

- 사용자명이 `postgres`가 아니라 **`postgres.<프로젝트ref>`** 형식이다. 복사한 문자열을
  그대로 쓰면 되고, 직접 조립하지 말 것.
- 두 풀러 모드 모두 동작하도록 `app/db.py`에서 `statement_cache_size=0`을 준다.
  트랜잭션 모드는 prepared statement를 지원하지 않아 이 설정이 없으면 깨진다.
- 프로젝트 URL(`https://<ref>.supabase.co`)은 **REST API 주소지 접속 문자열이 아니다.**
  `DATABASE_URL`에 넣으면 연결되지 않는다.

### 6-2. Render 환경변수

| 키 | 값 |
|---|---|
| `DATABASE_URL` | 위에서 복사한 접속 문자열 (`?sslmode=require` 포함) |
| `COLLECT_TOKEN` | 새로 만든 임의 문자열. **`API_TOKEN`과 다른 값** |
| `COLLECT_DISTRICTS` | 비워둔다(회랑 기본값 19곳) |

⚠ `COLLECT_TOKEN`을 `API_TOKEN`과 같게 두면 안 된다. `API_TOKEN`은 프런트 번들에
노출되므로, 페이지를 연 사람이면 누구나 수집을 트리거해 공공 API 쿼터를 태울 수 있다.

저장하면 Render가 자동 재시작하고, 기동 시 `app/schema.sql`이 한 번 실행되어
테이블이 만들어진다(이미 있으면 아무 일도 안 한다).

### 6-3. 크론 2개

**(a) 수집 — 5분마다** (기존 `/health` keep-alive 크론을 이것으로 **대체**한다)

```
POST https://<백엔드>.onrender.com/internal/collect
헤더: X-Collect-Key: <COLLECT_TOKEN>
주기: 매 5분
```

주기를 **10분보다 길게 잡으면 안 된다.** 공공 API 상태 피드의 윈도가 10분 고정이라
그 사이 변경분을 영구히 놓친다. 5분은 2배로 겹쳐 읽어 크론 지연에도 결측이 없게 한 값이다.

**(b) 집계 — 하루 1회 (KST 새벽 4시 권장)**

```
POST https://<백엔드>.onrender.com/internal/aggregate
헤더: X-Collect-Key: <COLLECT_TOKEN>
주기: 매일 04:00 (KST)
```

### 6-4. 동작 확인

먼저 접속부터 확인한다. 이 스크립트는 **비밀번호를 출력하지 않는다**(호스트·포트만).

```bash
cd backend && python check_db.py
```

```
대상: aws-0-ap-northeast-2.pooler.supabase.com:5432  DB=postgres
  Supavisor 세션 풀러 (포트 5432) — 둘 다 지원합니다.
✓ 연결 성공 — PostgreSQL 15.x
  테이블: occupancy_stat, session
  세션 0건 / 충전소 0곳 / 최초관측 -
  집계 셀 0개 (예측에 실제로 쓰이는 셀 0개)
```

연결이 되면 크론을 건다.

```bash
curl -s -X POST -H "X-Collect-Key: <COLLECT_TOKEN>" \
  https://<백엔드>.onrender.com/internal/collect
# {"ok":true,"feed_rows":13125,"targets":500,"sessions_seen":348,"budget_left":1998}
```

`targets`가 **500 근처**여야 정상이다(회랑 19개 시군구 기준 실측).
크게 벗어나면 저장량 추정(3.2MB/일 · 90일 290MB)이 무너지므로
`collector._MIN_POWER_KW` 또는 `COLLECT_DISTRICTS`를 조정한다.

첫 호출은 카탈로그 19개 시군구를 만드느라 **20초 안팎** 걸린다(이후 24시간 캐시).
크론 타임아웃을 30초 이상으로 잡을 것.

`ok:false`일 때의 `reason`:

| reason | 뜻 |
|---|---|
| `db_unavailable` | `DATABASE_URL` 미설정이거나 연결 실패 |
| `ev_api_key_missing` | `EV_STATION_API_KEY` 미설정 |
| `daily_budget_exhausted` | 자체 일일 예산 소진 (KST 자정에 리셋) |
| `no_targets` | 카탈로그에서 대상 충전소를 못 찾음 |
| `already_running` | 이전 수집이 아직 도는 중(정상. 다음 발화가 처리) |

집계 결과의 `cells_ready`가 **예측에 실제로 쓰이는 셀 수**다.

```bash
curl -s -X POST -H "X-Collect-Key: <COLLECT_TOKEN>" \
  https://<백엔드>.onrender.com/internal/aggregate
# {"ok":true,"cells":217,"cells_ready":0,"sessions":820,"pruned":"DELETE 0"}
```

**수집 초기에 `cells_ready`가 0인 것이 정상이다.** 첫 수집 때 각 충전기의 직전
세션이 함께 들어오지만(백필) 그 기간을 관측한 건 아니라서, 집계는 `station_seen`에
기록된 관측 시작 이후만 쓴다. 여기서 0이 아닌 큰 값이 바로 나온다면 그건 근거 없는
예측이라는 뜻이다.

> `/internal/*`은 **분당 2회** 제한이다. `collect`와 `aggregate`를 연달아 부르면
> 세 번째 호출이 429로 막힌다 — 수동 점검 시에는 1분 간격을 둔다.

### 6-5. 언제부터 화면에 나오나

관측일이 임계(8일) 미만이면 예측하지 않고 표시도 하지 않는다 — **추측값을 내지 않는
것이 설계 의도다.** 평일 시간대는 약 2주, 주말은 약 4주 뒤부터 `cells_ready`가 오르고
계획 화면에 혼잡 배지가 붙기 시작한다. 연휴는 통계가 쌓일 때까지 주말 통계로 대체하며,
그 경우 화면에 "주말 기준"이라고 함께 표기된다.

### 6-6. 쿼터 영향

| 항목 | 일 호출 |
|---|---|
| 상태 피드 (2페이지 × 5분 주기) | 576 |
| 회랑 카탈로그 (24h 캐시) | 20 |
| 기존 사용자 트래픽 | ~300 |
| **합계** | **약 900 / 10,000 = 9%** |

---

## 7. 배포 후 점검

```bash
# 1) 백엔드 살아있는지
curl https://<백엔드>.onrender.com/health

# 2) 토큰 없이 막히는지 (401이 나와야 정상)
curl -o /dev/null -w "%{http_code}\n" https://<백엔드>.onrender.com/api/stations/TEST

# 3) 운영 모드에서 API 문서가 닫혔는지 (404여야 정상)
curl -o /dev/null -w "%{http_code}\n" https://<백엔드>.onrender.com/docs
```

아이폰 Safari에서:
- 경로 계산이 되는가 (안 되면 `NEXT_PUBLIC_API_BASE`가 http이거나 CORS 오리진 불일치)
- 지도가 뜨는가 (안 뜨면 카카오 플랫폼 도메인 미등록)
- 입력창을 눌렀을 때 화면이 확대되지 않는가 (입력 폰트 16px 적용됨)

---

## 알아둘 한계

- **URL을 공유하지 말 것.** `NEXT_PUBLIC_API_TOKEN`은 번들에 노출되므로 페이지를 연 사람은 토큰을 볼 수 있다. 봇·스캐너 차단용이지 사람 대상 인증이 아니다. 진짜 차단이 필요하면 Vercel의 Deployment Protection이나 Cloudflare Access를 앞단에 둔다.
- **외부 API 일일 쿼터**가 있다. 경로계산 1회가 카카오 지오코딩 2 + 경로 1 + 좌표변환 최대 30여 회 + 공공 EV API 시군구별 수 회를 부른다. 쿼터를 넘기면 화면에 "사용량이 초과하였습니다"가 뜬다.
- **Vercel Hobby는 비상업 전용**이다. 수익이 발생하는 용도면 Pro로 올려야 한다.
- 오프라인 대응(서비스워커)이 없어 터널·음영지역에서 앱을 새로 열면 오류 화면이 뜬다.
