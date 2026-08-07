# Haji Charge Route

BYD 돌핀 전기차 **충전 경로 안내 웹앱** (PPT 기획 기반).

출발지·도착지·현충전량을 입력하면 BYD 돌핀 스탠다드 기준으로 경로 상
**필요한 충전 횟수(충전예상지점수)** 를 계산하고, 지도에 경로·충전소를 표시하며,
충전소별 **실시간 충전현황**을 보여준다.

## 문서 (인수인계)

| 문서 | 내용 |
|---|---|
| [01 앱기능설계서](docs/01-앱기능설계서.md) | 기능 목록·도메인 모델·계산 알고리즘·업무규칙·오류정책 |
| [02 화면기능정의서](docs/02-화면기능정의서.md) | 화면별 UI 요소·이벤트·검증·상태·전환 |
| [03 시스템아키텍처](docs/03-시스템아키텍처.md) | 하드웨어/인프라·모듈 구조·캐시·시퀀스·구조 부채 |
| [04 운영이슈](docs/04-운영이슈.md) | 속도·보안 이슈, 점검 체크리스트, **건드리면 안 되는 설정** |
| [05 품질처리내역](docs/05-품질처리내역.md) | 보안·성능·접근성·호환성 처리 내역과 미적용 사유 |
| [06 확장기획 — 성수기 혼잡](docs/06-확장기획-성수기혼잡.md) | 충전소 대기열 예측·출발시각 추천·지역 탐색 지도 개발 프롬프트 |
| [07 확장설계·구현 — 성수기 혼잡](docs/07-확장설계안-성수기혼잡.md) | 충전 대기 예측 설계·구현 (DB 선택·쿼터 역산·콜드스타트·배포 형태) |
| [DEPLOY.md](DEPLOY.md) | 배포 절차 (Vercel + Render + keep-alive 크론) |
| [TODO.md](TODO.md) | 인수 직후 처리할 잔여 작업 |

## 구조

```
haji-charge-route/
├── backend/    FastAPI — 충전 지점 계산 로직 + 경로/충전소 API
├── frontend/   Next.js 15 (App Router, TS, Tailwind, 카카오맵)
└── docs/       설계·운영 문서
```

- **프론트/백엔드 분리**: 프론트는 백엔드(REST)만 호출. 공공 API 키·CORS는
  백엔드에서 처리한다.
- **키 없이도 구동**: Kakao / 공공 충전소 API 키가 없으면 목(mock) 데이터로 동작.

## 화면 (PPT 4단계)

| 경로 | 화면 | 내용 |
|------|------|------|
| `/login` | 로그인 | 로고 + 로그인 버튼 → 메인 |
| `/main` | 메인 | 출발지·도착지·현충전량 입력 → 충전예상지점수 계산, 지도보기 |
| `/map` | 지도보기 | 경로 폴리라인 + 충전소 마커 (클릭 → 상세) |
| `/stations/[id]` | 충전소 상세 | 충전기 종류·제휴카드·멤버십·실시간 충전현황, **T맵 길안내 연결** |
| `/explore` | 지역 충전소 탐색 | 경로와 무관하게 시·군·구 단위로 충전소 조회 (클러스터 지도) |

## 실행

### 1) 백엔드 (FastAPI, 포트 8000)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # 필요 시 API 키 입력 (없어도 목으로 동작)
uvicorn app.main:app --reload --port 8000
```

- API 문서: http://localhost:8000/docs

### 2) 프론트엔드 (Next.js, 포트 3000)

```bash
cd frontend
npm install
copy .env.local.example .env.local   # NEXT_PUBLIC_KAKAO_JS_KEY 입력 시 실제 지도 표시
npm run dev
```

- 앱: http://localhost:3000

## API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/route/plan` | `{origin, destination, current_charge_pct}` → 경로 + 충전예상지점수 |
| `POST` | `/api/route/depart-options` | 출발 시각(±3h)별 총 소요시간 비교 |
| `GET` | `/api/stations/district` | 좌표가 속한 시·군·구 전체 충전소 (지역 탐색) |
| `GET` | `/api/stations/{id}` | 충전소 상세 + 실시간 충전현황 |
| `GET` | `/health` | 상태 및 키 설정 여부 |
| `POST` | `/internal/collect` | 충전 세션 수집 (크론 전용, `X-Collect-Key`) |
| `POST` | `/internal/aggregate` | 혼잡 통계 재집계 (크론 전용, 하루 1회) |

## 충전 계산 로직 (`backend/app/services/charging.py`)

BYD 돌핀 스탠다드 = 정격(만충) 주행 300km, 안전 마진 10%, 급속 충전 목표 80%.
(코드 기준값 `charging.py`의 `DOLPHIN_STANDARD.range_km=300.0`과 일치)

1. **단순 계산** — 현충전량으로 안전 마진 전까지 갈 수 있는 거리를 구하고,
   부족분을 충전 1회당 확보 거리로 나눠 필요 충전 횟수를 산출.
2. **충전소 매핑** — 각 충전 예상 지점을 경로에서 가까운(그 지점 이전의)
   실제 충전소에 배정. 같은 충전소 중복 배정은 제외.

> 차량 스펙은 `DOLPHIN_STANDARD` 상수에서 조정 가능.

## 실 데이터 연동 (API 키 발급 → .env 설정)

세 개의 키를 발급받아 넣으면 목 데이터 대신 실제 데이터로 동작한다.
(키가 없으면 자동으로 목 폴백)

### 1) Kakao (경로 · 지오코딩 · 지도)

1. https://developers.kakao.com → 내 애플리케이션 → 애플리케이션 추가
2. **REST API 키** → `backend/.env` 의 `KAKAO_REST_API_KEY`
   (경로·주소검색·좌표→시도코드 변환에 사용)
3. **JavaScript 키** → `frontend/.env.local` 의 `NEXT_PUBLIC_KAKAO_JS_KEY`
4. 앱 설정 → 플랫폼 → Web 에 `http://localhost:3000` 등록 (지도 표시용)
5. 카카오 내비(길찾기) API 사용 신청 필요:
   [Kakao Mobility Directions](https://developers.kakaomobility.com/)

### 2) 한국환경공단 전기차 충전소 정보 (공공데이터포털)

1. https://www.data.go.kr/data/15076352/openapi.do → **활용신청**
2. 승인 후 마이페이지 → 인증키의 **일반 인증키(Decoding)** 복사
   → `backend/.env` 의 `EV_STATION_API_KEY`
   > ⚠️ 반드시 **Decoding** 키를 사용 (Encoding 키를 넣으면 이중 인코딩되어 실패)

### 설정 후 확인

```bash
curl http://localhost:8000/health
# {"status":"ok","kakao":true,"ev_api":true} 이면 연동 준비 완료
```

- 실제 데이터 응답 시 `data_source` 가 경로는 `"kakao"`, 충전소 상세는 `"public_api"` 로 표시된다.

### 구현 위치 / 참고

| 파일 | 역할 |
|------|------|
| `backend/app/services/kakao.py` | 경로(directions)·지오코딩·좌표→시도코드(coord2regioncode) |
| `backend/app/services/ev_stations.py` | `getChargerInfo` 시도(zcode)별 조회 → 경로 인근 필터 → 실시간 상태 |

**PPT 속성 → 실제 용어 검증 결과 (코드 반영됨)**

| PPT 속성 | 실제 용어 / API 필드 | 코드 속성 |
|----------|----------------------|-----------|
| 충전기기종류 | 충전기 타입 (`chgerType`) | `charger_types` |
| **제휴카드** | **결제 수단** (환경부 로밍 '전기차이음' 등) | `payment_methods` |
| **충전유무(Y/N)** | **충전 상태** (`stat`: 충전가능/충전중/…) | `status` |
| **멤버쉽가입유무** | **이용 제한** (인가자외 사용제한, `limitYn`) | `usage_restricted` |
| 잔여시간 | (공공 API 미제공) | `remaining` = `None` |

**공공 API 제약**
- **결제 수단**·**잔여시간**은 공공 API가 제공하지 않아 각각 기본값(`환경부통합`, `EV CHARGE`)·`None`으로 둔다. 별도 데이터 소스가 있으면 그 지점을 교체.
- 충전기 타입: `chgerType == "02"`(AC완속) → 완속, 그 외 → 급속.
- 충전 상태(`stat`): `2`→충전가능, `3`→충전중, `4`→운영중지, `5`→점검중, `1`/`9`→상태미확인.
