# 남은 작업 (2026-07-31 세션 인수인계)

배포는 끝났고 동작한다. 아래는 아직 손대지 않았거나 사용자 확인이 필요한 것들.

## 지금 바로 해야 할 것

- [ ] **cron-job.org URL 오타 수정** — `/heath` → `/health`
      (404여도 서비스는 깨지만, 계속 실패하면 잡이 자동 비활성화될 수 있음)
- [ ] **카카오 REST API 키 재발급** — 스크린샷으로 노출됨.
      재발급 후 Render 환경변수 `KAKAO_REST_API_KEY` 교체 (저장하면 자동 재시작)
- [ ] **공공 EV API 키 재발급** — 2026-08-04 세션에서 `getChargerStatus` 검증 중 평문 노출됨.
      재발급 후 Render 환경변수 `EV_STATION_API_KEY` 교체.
      ⚠ 반드시 **일반 인증키(Decoding)** 를 넣을 것 (Encoding 키는 이중 인코딩되어 실패)
- [ ] **카카오 JavaScript 키에 도메인 등록 확인** — 지도가 안 뜨면 이것.
      경로: 앱 설정 → 앱 → 플랫폼 키 → **JavaScript 키** → JavaScript SDK 도메인
      값: `https://haji-charge-route.vercel.app`
      (REST 키 화면이 아니다. REST 키의 "호출 허용 IP"는 비워 둘 것 — Render 무료는 IP 고정 아님)
- [ ] **아이폰에서 계산 재테스트** — 타임아웃 120초 반영 후 정상 동작 확인

## 배포 정보

| | |
|---|---|
| 프런트 | https://haji-charge-route.vercel.app (Vercel Hobby, Root Directory=`frontend`) |
| 백엔드 | https://haji-charge-route-api.onrender.com (Render Free, Singapore, `render.yaml` Blueprint) |
| 저장소 | Lucia2959/haji-charge-route (main) |

환경변수는 [DEPLOY.md](DEPLOY.md) 참고. `NEXT_PUBLIC_*`은 빌드 시 굳으므로 값 변경 후 반드시 Redeploy.

## 알려진 제약 (수정 아님, 인지용)

- **첫 계산은 최대 1분** — 경로가 지나는 시군구 20여 곳의 충전소 목록을 받기 때문.
  캐시(24h)가 살아있으면 훨씬 빠름. keep-alive 크론이 이걸 유지시킨다.
- **공공 EV API 일일 쿼터** — 계산 1회 = 시군구 약 20~24회 호출.
  소진되면 화면에 "사용량이 초과하였습니다"(HTTP 402). 일 단위로 리셋.
  한도 확인·증량: 공공데이터포털 마이페이지 → 오픈API → 활용신청 현황
- **동시성 상한을 올리지 말 것** — `_FETCH_CONCURRENCY=4`. 실측상 8이면 즉시 차단됨.
- **URL 공유 금지** — `NEXT_PUBLIC_API_TOKEN`이 번들에 노출됨(봇 차단용이지 인증 아님).
- 오프라인 대응(서비스워커) 없음 — 터널·음영지역에서 앱을 새로 열면 오류 화면.

## 검토에서 나왔으나 미적용 (필요하면 그때)

- CSP 헤더 추가 (카카오 SDK가 인라인 스크립트를 써서 `'unsafe-inline'` 필요)
- 서비스워커(오프라인 셸)
- 접근성 중간순위 잔여: 이모지 `aria-hidden`, 모달 결과 수 안내,
  RouteStrip 구간에 `sr-only` 설명, 충전소 표 `role="button"` 행 → 셀 안 버튼으로
- `charge/page.tsx` 단위 토글을 `role="radiogroup"`으로

## 자체검증 (변경 후 반드시 실행)

```bash
cd backend
python test_planning.py            # 안전마진·접근성분류·목적지 최소잔량·직행 선충전
python test_consumption.py         # 소비모델(온도/속도/회생), 출발 선충전 공식
python test_external_stability.py  # 재시도·쿼터소진(402) vs 일시제한(429) 구분
python test_congestion.py          # 혼잡 예측 콜드스타트·추정식·성수기 회귀·zscode 정규화
cd ../frontend && npx tsc --noEmit
```
