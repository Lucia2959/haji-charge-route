"""환경변수 설정 (pydantic-settings).

값의 출처는 두 가지다.
  · 로컬 : `backend/.env` (gitignore 대상. 템플릿은 `.env.example`)
  · 배포 : Render 대시보드의 환경변수 (`render.yaml`에서 `sync: false`로 선언)

모듈 로드 시점에 단일 인스턴스 `settings`를 만들어 앱 전역이 공유한다. 즉
**환경변수 변경은 프로세스 재시작이 있어야 반영된다**(Render는 값 저장 시 자동 재시작).

키가 비어 있어도 앱은 뜬다 — `use_kakao` / `use_ev_api`가 False가 되어 mock으로
동작한다. 단 운영에서는 `mock_enabled=False`라 mock 폴백 대신 오류를 낸다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kakao_rest_api_key: str = ""
    ev_station_api_key: str = ""
    frontend_origin: str = "http://localhost:3000"
    # 운영/개발 구분: production일 때 /docs 비활성화. mock_enabled=False면
    # 외부 API 실패 시 mock으로 조용히 폴백하지 않고 오류를 반환한다.
    app_env: str = "development"
    mock_enabled: bool = True
    # 공유 시크릿. 설정하면 /api/* 요청에 X-Haji-Key 헤더를 요구한다.
    # 프런트에도 넣어야 하므로 번들에 노출된다 → 사람 대상 인증이 아니라, URL을 모르는
    # 봇·스캐너가 외부 API 쿼터를 태우는 것을 막는 1차 차단용이다. 비우면 검사 안 함.
    api_token: str = ""

    # --- 충전 혼잡 예측 (docs/07) --------------------------------------------
    # Postgres 접속 문자열. 비어 있으면 혼잡 예측 기능만 조용히 꺼지고 나머지는 그대로
    # 동작한다(로컬 개발·DB 미프로비저닝 상태에서도 앱이 떠야 한다).
    # SQLite를 쓰지 않는 이유: Render 무료는 파일시스템이 휘발성이라 재배포마다
    # 수집 이력이 사라진다 → 콜드스타트가 끝나지 않는다. docs/07 §3-1.
    database_url: str = ""
    # 수집 트리거 전용 토큰. api_token과 반드시 다른 값이어야 한다 —
    # api_token은 프런트 번들에 노출되므로, 그걸로 수집을 부를 수 있으면
    # 누구나 공공 API 쿼터를 태울 수 있다.
    collect_token: str = ""
    # 세션을 저장할 시군구. "zcode:zscode" 쉼표 구분. 비우면 아래 회랑 기본값.
    # 전국 상태 피드는 어차피 통째로 받지만(호출 2회), 저장까지 전국으로 하면
    # 무료 Postgres 500MB를 4개월이면 채운다 → 저장 대상만 좁힌다. docs/07 §3-2.
    collect_districts: str = ""
    # 수집기 일일 호출 예산. 초과하면 그날 수집을 멈춘다 — 계획 API가 쓸 쿼터를
    # 수집기가 먼저 태워버리는 상황을 막는 안전장치. 5분 주기 × 2페이지 = 576/일이라
    # 2000이면 3배 여유. 공공 API 한도(개발계정 10,000/일)와는 별개의 자체 상한이다.
    collect_daily_budget: int = 2000

    @property
    def use_db(self) -> bool:
        return bool(self.database_url)

    @property
    def use_kakao(self) -> bool:
        return bool(self.kakao_rest_api_key)

    @property
    def use_ev_api(self) -> bool:
        return bool(self.ev_station_api_key)

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() in ("production", "prod")


settings = Settings()
