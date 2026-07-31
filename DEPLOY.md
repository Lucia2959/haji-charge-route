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

### 콜드스타트 주의

Render 무료는 **15분 무요청 시 잠들고, 다음 요청에 30~60초** 걸린다. 여기에 앱의 첫 경로계산(카탈로그 빌드 ~14초)이 더해져 **첫 사용이 최대 1분 이상** 걸릴 수 있다.

- 출발 직전에 쓰는 앱이라 이게 가장 거슬리는 부분이다.
- 완화: 무료 크론(cron-job.org, UptimeRobot 등)으로 `/health`를 10분마다 호출해 깨워둔다. Render 무료는 월 750 인스턴스시간이고 한 달은 ~730시간이라, **서비스 1개는 상시 가동해도 쿼터 안에 든다.**
- 완전히 없애려면 Render Starter(약 $7/월).

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

Kakao Developers → 내 애플리케이션 → 앱 설정 → **플랫폼 → Web → 사이트 도메인**에
`https://<프로젝트>.vercel.app` 추가.

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

## 6. 배포 후 점검

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
