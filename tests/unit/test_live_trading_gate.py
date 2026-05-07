"""Unit tests for LIVE_TRADING gate and startup validation."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.core.execution import Executor, OrderIntent
from src.orchestrator.main import _validate_startup


def _make_intent() -> OrderIntent:
    return OrderIntent(
        ticker="DEMO-TEST",
        side="yes",
        action="buy",
        price_dollars=Decimal("0.50"),
        count=1,
    )


def _make_settings(**kwargs: object) -> MagicMock:
    s = MagicMock()
    s.KALSHI_ENV = kwargs.get("KALSHI_ENV", "demo")
    s.LIVE_TRADING = kwargs.get("LIVE_TRADING", False)
    s.KALSHI_API_KEY_ID_DEMO = kwargs.get("KALSHI_API_KEY_ID_DEMO", "demo-key")
    s.KALSHI_PRIVATE_KEY_PATH_DEMO = kwargs.get("KALSHI_PRIVATE_KEY_PATH_DEMO", "/tmp/demo.pem")
    s.KALSHI_API_KEY_ID_PROD = kwargs.get("KALSHI_API_KEY_ID_PROD", "")
    s.KALSHI_PRIVATE_KEY_PATH_PROD = kwargs.get("KALSHI_PRIVATE_KEY_PATH_PROD", "")
    s.kalshi_rest_base_url = "https://demo-api.kalshi.co/trade-api/v2"
    s.kalshi_ws_url = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    s.ORDER_RETRY_MAX_ATTEMPTS = 1
    s.ORDER_RETRY_BACKOFF_BASE_MS = 1
    s.ORDER_TIMEOUT_S = 5.0
    return s


def test_paper_mode_no_api_call() -> None:
    """LIVE_TRADING=false → submit routes to paper engine, client.place_order never called."""
    client = MagicMock()
    settings = _make_settings(LIVE_TRADING=False)
    executor = Executor(client=client, settings=settings)
    outcome = executor.submit(_make_intent())
    assert outcome.status == "paper"
    client.place_order.assert_not_called()


def test_live_trading_with_demo_env_raises() -> None:
    """LIVE_TRADING=true + KALSHI_ENV=demo → RuntimeError at startup."""
    settings = _make_settings(LIVE_TRADING=True, KALSHI_ENV="demo")
    with patch("os.path.isfile", return_value=True), pytest.raises(RuntimeError, match="demo cannot accept real orders"):
        _validate_startup(settings)


def test_prod_env_missing_key_raises() -> None:
    """KALSHI_ENV=prod + empty prod key → RuntimeError at startup."""
    settings = _make_settings(
        KALSHI_ENV="prod",
        KALSHI_API_KEY_ID_PROD="",
        KALSHI_PRIVATE_KEY_PATH_PROD="",
    )
    with pytest.raises(RuntimeError, match="KALSHI_API_KEY_ID_PROD is not set"):
        _validate_startup(settings)


def test_demo_env_missing_key_raises() -> None:
    """KALSHI_ENV=demo + empty demo key → RuntimeError at startup."""
    settings = _make_settings(
        KALSHI_ENV="demo",
        KALSHI_API_KEY_ID_DEMO="",
    )
    with pytest.raises(RuntimeError, match="KALSHI_API_KEY_ID_DEMO is not set"):
        _validate_startup(settings)
