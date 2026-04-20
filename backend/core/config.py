from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OUTLAND_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "Outland Backend"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/outland.db"

    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"

    HEARTBEAT_TIMEOUT: int = 180
    HEARTBEAT_CLEANUP_INTERVAL: int = 60

    HTTP_MAX_KEEPALIVE: int = 20
    HTTP_MAX_CONNECTIONS: int = 100
    HTTP_KEEPALIVE_EXPIRY: float = 30.0

    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
