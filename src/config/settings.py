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
    LIVE_TRADING: bool = False

    # Credentials (per env)
    KALSHI_API_KEY_ID_DEMO: str | None = None
    KALSHI_PRIVATE_KEY_PATH_DEMO: str | None = None
    KALSHI_API_KEY_ID_PROD: str | None = None
    KALSHI_PRIVATE_KEY_PATH_PROD: str | None = None

    # Endpoints (per env)
    KALSHI_REST_BASE_URL_DEMO: str = "https://demo-api.kalshi.co/trade-api/v2"
    KALSHI_WS_URL_DEMO: str = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    KALSHI_REST_BASE_URL_PROD: str = "https://api.elections.kalshi.com/trade-api/v2"
    KALSHI_WS_URL_PROD: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"

    # Optional with defaults
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"
    DB_PATH: str = "./data/kalshi.db"

    # Phase 4 — execution engine
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

    # Phase 6 — reconciliation
    RECONCILE_INTERVAL_S: int = 60

    # Phase 8 — observability
    PROMETHEUS_PORT: int = 8000
    PROMETHEUS_ENABLED: bool = True

    # ------------------------------------------------------------------
    # Computed properties — select credential/URL based on KALSHI_ENV
    # ------------------------------------------------------------------

    @property
    def kalshi_api_key_id(self) -> str | None:
        return self.KALSHI_API_KEY_ID_DEMO if self.KALSHI_ENV == "demo" else self.KALSHI_API_KEY_ID_PROD

    @property
    def kalshi_private_key_path(self) -> str | None:
        return self.KALSHI_PRIVATE_KEY_PATH_DEMO if self.KALSHI_ENV == "demo" else self.KALSHI_PRIVATE_KEY_PATH_PROD

    @property
    def kalshi_rest_base_url(self) -> str:
        return self.KALSHI_REST_BASE_URL_DEMO if self.KALSHI_ENV == "demo" else self.KALSHI_REST_BASE_URL_PROD

    @property
    def kalshi_ws_url(self) -> str:
        return self.KALSHI_WS_URL_DEMO if self.KALSHI_ENV == "demo" else self.KALSHI_WS_URL_PROD


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
