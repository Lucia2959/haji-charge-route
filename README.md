# Haji Charge Route

BYD 돌핀 전기차 **충전 경로 안내 웹앱** (PPT 기획 기반).

출발지·도착지·현충전량을 입력하면 BYD 돌핀 스탠다드 기준으로 경로 상
**필요한 충전 횟수(충전예상지점수)** 를 계산하고, 지도에 경로·충전소를 표시하며,
충전소별 **실시간 충전현황**을 보여준다.

## 구조

```
haji-charge-route/
├── backend/    FastAPI — 충전 지점 계산 로직 + 경로/충전소 API
└── frontend/   Next.js 15 (App Router, TS, Tailwind, 카카오맵)
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
| `/stations/[id]` | 충전소 상세 | 충전기 종류·제휴카드·멤버십·실시간 충전현황 |

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
| `GET` | `/api/stations/{id}` | 충전소 상세 + 실시간 충전현황 |
| `GET` | `/health` | 상태 및 키 설정 여부 |

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
