"""Unit tests for Reconciler — divergence detection and DB correction."""
from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.reconcile import Reconciler, ReconcileResult
from src.storage.db import apply_schema


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_client(
    *,
    balance_cents: int = 100_000,
    positions: list[dict[str, Any]] | None = None,
    orders: list[dict[str, Any]] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.get_balance.return_value = {"balance": balance_cents}
    client.get_positions.return_value = {"market_positions": positions or []}
    client.get_orders.return_value = {"orders": orders or []}
    return client


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.RECONCILE_INTERVAL_S = 60
    return s


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    apply_schema(conn, "src/storage/schema.sql")
    return conn


def _seed_market(conn: sqlite3.Connection, ticker: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO markets (
            ticker, event_ticker, series_ticker, category, status,
            tick_size, price_level_structure, close_time_ms,
            first_seen_ms, last_refreshed_ms, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, "EVT-A", "SRS-A", "test", "open", "0.01", "{}", 9_999_999_999_000, 1_000_000, 1_000_000, "{}"),
    )
    conn.commit()


def _seed_resting_order(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    ticker: str = "DEMO-MKT-A",
) -> None:
    _seed_market(conn, ticker)
    conn.execute(
        """INSERT INTO orders (
            client_order_id, order_id, ticker, side, action,
            price_dollars, count, time_in_force, post_only,
            status, created_ts_ms, signal_module
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"coid-{order_id}", order_id, ticker, "yes", "buy",
            "0.50", 10, "GTC", 1, "resting", 1_000_000, "test",
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reconcile_once_returns_result(db: sqlite3.Connection) -> None:
    client = _make_client(balance_cents=50_000)
    r = Reconciler(client=client, settings=_make_settings(), db_conn=db)
    result = r.reconcile_once()
    assert isinstance(result, ReconcileResult)
    assert result.balance_cents == 50_000
    assert result.errors == []
    assert result.positions_corrected == 0
    assert result.orphan_orders_canceled == 0
    assert result.lost_orders_inserted == 0


def test_orphan_order_marked_canceled_by_exchange(db: sqlite3.Connection) -> None:
    _seed_resting_order(db, order_id="orphan-1")
    client = _make_client(orders=[])
    r = Reconciler(client=client, settings=_make_settings(), db_conn=db)
    result = r.reconcile_once()
    assert result.orphan_orders_canceled == 1
    row = db.execute(
        "SELECT status FROM orders WHERE order_id='orphan-1'"
    ).fetchone()
    assert row["status"] == "canceled_by_exchange"


def test_lost_order_inserted(db: sqlite3.Connection) -> None:
    _seed_market(db, "DEMO-MKT-B")
    exc_order = {
        "order_id": "exc-order-1",
        "client_order_id": "coid-exc-1",
        "ticker": "DEMO-MKT-B",
        "side": "yes",
        "action": "buy",
        "yes_price_dollars": "0.60",
        "count_fp": 5,
        "time_in_force": "GTC",
        "post_only": True,
    }
    client = _make_client(orders=[exc_order])
    r = Reconciler(client=client, settings=_make_settings(), db_conn=db)
    result = r.reconcile_once()
    assert result.lost_orders_inserted == 1
    row = db.execute(
        "SELECT status, ticker FROM orders WHERE order_id='exc-order-1'"
    ).fetchone()
    assert row is not None
    assert row["status"] == "resting"
    assert row["ticker"] == "DEMO-MKT-B"


def test_position_without_order_logs_warning(db: sqlite3.Connection) -> None:
    client = _make_client(
        positions=[{"ticker": "DEMO-MKT-C", "position": 5}]
    )
    r = Reconciler(client=client, settings=_make_settings(), db_conn=db)
    result = r.reconcile_once()
    assert result.positions_corrected == 1
    assert result.errors == []


def test_step_error_captured_not_raised(db: sqlite3.Connection) -> None:
    client = _make_client()
    client.get_balance.side_effect = RuntimeError("network timeout")
    r = Reconciler(client=client, settings=_make_settings(), db_conn=db)
    result = r.reconcile_once()
    assert len(result.errors) == 1
    assert "balance" in result.errors[0]
    assert result.positions_corrected == 0
    assert result.orphan_orders_canceled == 0


def test_force_reconcile_equivalent_to_reconcile_once(
    db: sqlite3.Connection,
) -> None:
    client = _make_client(balance_cents=75_000)
    r = Reconciler(client=client, settings=_make_settings(), db_conn=db)
    result = r.force_reconcile()
    assert isinstance(result, ReconcileResult)
    assert result.balance_cents == 75_000
    assert result.errors == []
