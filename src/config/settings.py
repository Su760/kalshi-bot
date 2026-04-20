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

    # Phase 5 — risk layer
    MAX_DAILY_LOSS_USD: float = 50.0
    MAX_PER_MARKET_CONTRACTS: int = 100
    MAX_PER_EVENT_PCT: float = 0.10
    MAX_DRAWDOWN_PCT: float = 0.05
    MAX_TOTAL_AT_RISK_PCT: float = 0.25
    HEARTBEAT_TIMEOUT_S: int = 60
    KELLY_FRACTION: float = 0.25
    MIN_EDGE_PCT: float = 0.08
    MIN_NET_EDGE_PCT: float = 0.02
    KILL_SWITCH_FILE: str = "./KILL"
    RISK_BALANCE_REFRESH_INTERVAL_S: int = 30

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
