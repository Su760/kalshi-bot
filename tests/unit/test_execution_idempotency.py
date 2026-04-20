"""Phase 4 unit tests — execution engine idempotency and paper-mode guarantees.

All tests mock the Kalshi client; no real API calls and no DB writes
(db_conn=None exercises the guard branches in _insert_pending / _update_outcome).
"""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest

from src.core.client import KalshiHTTPError
from src.core.execution import Executor, OrderIntent
from src.core.risk_stub import KillSwitchActive, RiskManagerStub


def _make_settings(*, live: bool = False) -> MagicMock:
    s = MagicMock()
    s.LIVE_TRADING = live
    s.ORDER_RETRY_MAX_ATTEMPTS = 3
    s.ORDER_RETRY_BACKOFF_BASE_MS = 1  # tiny backoff keeps tests fast
    s.ORDER_TIMEOUT_S = 5.0
    return s


def _make_intent(**overrides: object) -> OrderIntent:
    base: dict[str, object] = {
        "ticker": "DEMO-TEST",
        "side": "yes",
        "action": "buy",
        "price_dollars": Decimal("0.42"),
        "count": 10,
    }
    base.update(overrides)
    return OrderIntent(**base)  # type: ignore[arg-type]


def test_paper_trade_does_not_call_api() -> None:
    client = MagicMock()
    exec_ = Executor(client=client, settings=_make_settings(live=False))
    outcome = exec_.submit(_make_intent())
    assert outcome.status == "paper"
    client.place_order.assert_not_called()
    client.get_orders.assert_not_called()


def test_paper_trade_returns_client_order_id() -> None:
    client = MagicMock()
    exec_ = Executor(client=client, settings=_make_settings(live=False))
    outcome = exec_.submit(_make_intent())
    assert outcome.client_order_id
    assert len(outcome.client_order_id) == 32  # uuid4().hex
    assert outcome.order_id is None


def test_timeout_then_order_found_no_duplicate() -> None:
    """On transient timeout, we reconcile by client_order_id — no blind retry."""
    client = MagicMock()
    # First place_order call times out. The reconciliation GET finds the order.
    client.place_order.side_effect = httpx.TimeoutException("boom")
    client.get_orders.return_value = {
        "orders": [
            {
                "order_id": "kalshi-123",
                "client_order_id": "will-be-overwritten",
                "status": "resting",
                "filled_count_fp": 0,
            }
        ]
    }
    exec_ = Executor(client=client, settings=_make_settings(live=True))
    outcome = exec_.submit(_make_intent())
    assert outcome.status == "resting"
    assert outcome.order_id == "kalshi-123"
    # Exactly one place_order call — no duplicate.
    assert client.place_order.call_count == 1
    # Exactly one reconciliation GET.
    assert client.get_orders.call_count == 1


def test_terminal_reject_not_retried() -> None:
    """POST_ONLY_CROSS is terminal — return rejected outcome, no retry."""
    client = MagicMock()
    client.place_order.side_effect = KalshiHTTPError(400, "POST_ONLY_CROSS", "would cross")
    exec_ = Executor(client=client, settings=_make_settings(live=True))
    outcome = exec_.submit(_make_intent())
    assert outcome.status == "rejected"
    assert outcome.reject_code == "POST_ONLY_CROSS"
    assert client.place_order.call_count == 1


def test_kill_switch_blocks_submission() -> None:
    """RiskManager.check raising KillSwitchActive must propagate out of submit."""
    client = MagicMock()
    risk = MagicMock(spec=RiskManagerStub)
    risk.check.side_effect = KillSwitchActive("tripped")
    exec_ = Executor(
        client=client,
        settings=_make_settings(live=True),
        risk=risk,
    )
    with pytest.raises(KillSwitchActive):
        exec_.submit(_make_intent())
    client.place_order.assert_not_called()


def test_fixed_point_fields_in_request_body() -> None:
    """Order body must use count_fp and yes_price_dollars — never count/yes_price."""
    client = MagicMock()
    client.place_order.return_value = {
        "order": {
            "order_id": "kalshi-xyz",
            "status": "resting",
            "filled_count_fp": 0,
        }
    }
    exec_ = Executor(client=client, settings=_make_settings(live=True))
    exec_.submit(_make_intent(count=7, price_dollars=Decimal("0.33")))
    # Inspect the body passed to client.place_order.
    assert client.place_order.call_count == 1
    (body,), _ = client.place_order.call_args
    assert "count_fp" in body
    assert body["count_fp"] == 7
    assert "yes_price_dollars" in body
    assert body["yes_price_dollars"] == "0.33"
    # Deprecated fields MUST NOT be present.
    assert "count" not in body
    assert "yes_price" not in body
    # Sanity — other locked fields.
    assert body["type"] == "limit"
    assert body["post_only"] is True
    assert body["time_in_force"] == "GTC"
    assert body["self_trade_prevention_type"] == "cancel_resting"
    assert body["client_order_id"]
    # Entire body must be JSON-serialisable (httpx will do this; assert here).
    json.dumps(body)
