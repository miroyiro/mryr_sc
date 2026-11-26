from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """.env 값을 읽어오는 설정. 변수명 = .env 키 이름

    비밀 값은 SecretStr → print/log 해도 '**********' 로 나옴. 실제 값은 .get_secret_value()
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+asyncpg://dev:dev@localhost:5433/miroyiro"
    DB_POOL_SIZE: int = 5

    # 서버 간 인증 — 방향별로 키를 분리 (한쪽 키가 새도 반대 방향은 안전)
    INTERNAL_KEY: SecretStr = SecretStr("dev-internal-key")          # backend → scrap (받는 키)
    BACKEND_INTERNAL_KEY: SecretStr = SecretStr("dev-backend-key")   # scrap → backend (보내는 키)
    BACKEND_INTERNAL_URL: str = "http://localhost:8080"              # Spring. 운영: Tailscale 주소
    BACKEND_TIMEOUT_SEC: float = 10.0

    # 외부 API 키 (없어도 서버는 켜짐)
    KOPIS_API_KEY: SecretStr | None = None     # URL 쿼리(service=)로 나감 → 로그·에러에 남지 않게
    TMDB_API_KEY: SecretStr | None = None
    X_BEARER_TOKEN: SecretStr | None = None

    # 수집
    SCRAPER_USER_AGENT: str = "MiroyiroBot/0.1"
    HTTP_TIMEOUT_SEC: float = 15.0
    HTTP_MAX_RETRIES: int = 3
    SCHEDULER_ENABLED: bool = False
    PLAYWRIGHT_ENABLED: bool = False

    # AniList TTL (04 문서: releasing 1일 / finished 30일)
    ANILIST_TTL_RELEASING_HOURS: int = 24
    ANILIST_TTL_FINISHED_DAYS: int = 30

    @property
    def is_prod(self) -> bool:
        return self.APP_ENV == "prod"


settings = Settings()
