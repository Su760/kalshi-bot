"""Unit tests for OrchestratorLoop and ScanLoop — wiring + lifecycle."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.modules.base import Signal
from src.orchestrator.loop import ScanLoop
from src.orchestrator.main import OrchestratorLoop
from src.storage.db import apply_schema


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    apply_schema(conn, "src/storage/schema.sql")
    return conn


def _seed_market(conn: sqlite3.Connection, ticker: str = "DEMO-MKT-A") -> None:
    conn.execute(
        """INSERT OR IGNORE INTO markets (
            ticker, event_ticker, series_ticker, category, status,
            tick_size, price_level_structure, close_time_ms,
            first_seen_ms, last_refreshed_ms, raw_json,
            volume_24h, open_interest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker, "EVT-A", "SRS-A", "test", "open",
            "0.01", "{}", 9_999_999_999_000,
            1_000_000, 1_000_000, "{}",
            1000, 500,
        ),
    )
    conn.commit()


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.LIVE_TRADING = False
    s.KELLY_FRACTION = 0.25
    s.MAX_PER_MARKET_CONTRACTS = 100
    s.RECONCILE_INTERVAL_S = 60
    s.PROMETHEUS_PORT = 8000
    s.PROMETHEUS_ENABLED = False
    return s


def test_scan_loop_run_once_returns_zero_with_empty_books(
    db: sqlite3.Connection,
) -> None:
    scanner = MagicMock()
    scanner._books = {}
    executor = MagicMock()
    settings = _make_settings()

    loop = ScanLoop(
        scanner=scanner,
        executor=executor,
        db_conn=db,
        settings=settings,
    )
    assert loop.run_once() == 0
    executor.submit.assert_not_called()


def test_scan_loop_skips_markets_not_in_books(db: sqlite3.Connection) -> None:
    _seed_market(db, "DEMO-MKT-A")

    scanner = MagicMock()
    scanner._books = {}  # no live book for DEMO-MKT-A
    executor = MagicMock()
    settings = _make_settings()

    loop = ScanLoop(
        scanner=scanner,
        executor=executor,
        db_conn=db,
        settings=settings,
    )
    assert loop.run_once() == 0
    scanner.predict.assert_not_called()
    executor.submit.assert_not_called()


def test_scan_loop_fires_signal_when_book_present(db: sqlite3.Connection) -> None:
    _seed_market(db, "DEMO-MKT-A")

    book = MagicMock()
    ob = MagicMock()
    ob.yes_bids = [MagicMock(price=Decimal("0.40"), size=100)]
    book.to_orderbook.return_value = ob

    scanner = MagicMock()
    scanner._books = {"DEMO-MKT-A": book}
    scanner.applies_to.return_value = True
    scanner.predict.return_value = Signal(
        my_probability=0.70,
        confidence=0.8,
        data_freshness_seconds=1,
        source_module="scanner",
        debug={"detector": "thin_spread", "net_edge": 0.25},
    )

    executor = MagicMock()
    executor.submit.return_value = MagicMock(status="resting")
    settings = _make_settings()

    loop = ScanLoop(
        scanner=scanner,
        executor=executor,
        db_conn=db,
        settings=settings,
    )
    fired = loop.run_once()
    assert fired == 1
    executor.submit.assert_called_once()
    intent = executor.submit.call_args[0][0]
    assert intent.ticker == "DEMO-MKT-A"
    assert intent.side == "yes"
    assert intent.action == "buy"
    assert intent.count > 0


def test_orchestrator_stop_sets_running_false() -> None:
    settings = _make_settings()
    orch = OrchestratorLoop(settings)
    orch._running = True
    orch.stop()
    assert orch._running is False
