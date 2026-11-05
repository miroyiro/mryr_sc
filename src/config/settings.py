from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """.env 값을 읽어오는 설정. 변수명 = .env 키 이름"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://dev:dev@localhost:5433/miroyiro"
    INTERNAL_KEY: str = "dev-internal-key"
    BACKEND_INTERNAL_URL: str = "http://localhost:3000"

    # 외부 API 키 (없어도 서버는 켜짐)
    KOPIS_API_KEY: str | None = None
    TMDB_API_KEY: str | None = None
    X_BEARER_TOKEN: str | None = None


settings = Settings()
