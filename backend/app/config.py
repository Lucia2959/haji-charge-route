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
