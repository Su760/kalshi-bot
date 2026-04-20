from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Required
    KALSHI_ENV: Literal["demo", "prod"]
    KALSHI_API_KEY_ID: str
    KALSHI_PRIVATE_KEY_PATH: str
    KALSHI_REST_BASE_URL: str
    KALSHI_WS_URL: str

    # Optional with defaults
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"
    DB_PATH: str = "./data/kalshi.db"

    # Phase 4 — execution engine
    LIVE_TRADING: bool = False
    ORDER_RETRY_MAX_ATTEMPTS: int = 3
    ORDER_RETRY_BACKOFF_BASE_MS: int = 200
    ORDER_TIMEOUT_S: float = 5.0

    def model_post_init(self, __context: object) -> None:
        if self.KALSHI_ENV == "prod":
            assert "demo" not in self.KALSHI_REST_BASE_URL.lower(), \
                "KALSHI_ENV=prod but base URL contains 'demo'"
            assert "demo" not in self.KALSHI_WS_URL.lower(), \
                "KALSHI_ENV=prod but WS URL contains 'demo'"
        if self.KALSHI_ENV == "demo":
            assert "demo" in self.KALSHI_REST_BASE_URL.lower(), \
                "KALSHI_ENV=demo but base URL does not contain 'demo'"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
