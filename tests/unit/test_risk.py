"""Phase 5 unit tests — six-tier RiskManager kill switch stack.

Covers every tier plus trip() idempotency and KILL file creation.
Uses in-memory SQLite (shared by URI) so heartbeat/orders/markets lookups work.
No real Kalshi API calls — client is a MagicMock.
"""
from __future__ import annotations

import os
import sqlite3
import time
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.execution import OrderIntent
from src.core.risk import RiskManager
from src.core.risk_stub import KillSwitchActive, RiskError
from src.storage.db import apply_schema


def _make_settings(**overrides: Any) -> MagicMock:
    s = MagicMock()
    s.MAX_DAILY_LOSS_USD = 50.0
    s.MAX_PER_MARKET_CONTRACTS = 100
    s.MAX_PER_EVENT_PCT = 0.10
    s.MAX_DRAWDOWN_PCT = 0.05
    s.MAX_TOTAL_AT_RISK_PCT = 0.25
    s.HEARTBEAT_TIMEOUT_S = 60
    s.KELLY_FRACTION = 0.25
    s.MIN_EDGE_PCT = 0.08
    s.MIN_NET_EDGE_PCT = 0.02
    s.KILL_SWITCH_FILE = "./KILL_TEST"
    s.RISK_BALANCE_REFRESH_INTERVAL_S = 30
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_client(balance_cents: int = 100_000) -> MagicMock:
    client = MagicMock()
    client.get_balance.return_value = {"balance": balance_cents}
    return client


def _make_intent(**overrides: Any) -> OrderIntent:
    base: dict[str, Any] = {
        "ticker": "DEMO-MKT-A",
        "side": "yes",
        "action": "buy",
        "price_dollars": Decimal("0.50"),
        "count": 10,
    }
    base.update(overrides)
    return OrderIntent(**base)


@pytest.fixture
def db() -> sqlite3.Connection:
    """In-memory DB with full schema applied."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_schema(conn, "src/storage/schema.sql")
    return conn


@pytest.fixture
def kill_file(tmp_path: Any) -> str:
    return str(tmp_path / "KILL")


# ----------------------------------------------------------------------
# Tier 1 — kill flag (file + in-memory)
# ----------------------------------------------------------------------


def test_tier1_in_memory_kill_flag_raises(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm._killed = True
    with pytest.raises(KillSwitchActive):
        rm.check(_make_intent())


def test_tier1_kill_file_present_raises(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    with open(kill_file, "w") as f:
        f.write("prior trip\n")
    with pytest.raises(KillSwitchActive):
        rm.check(_make_intent())


# ----------------------------------------------------------------------
# Tier 2 — daily loss cap
# ----------------------------------------------------------------------


def test_tier2_daily_loss_under_cap_passes(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client(balance_cents=100_000)
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, MAX_DAILY_LOSS_USD=50.0)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    # Simulate a small loss (-$10).
    rm._balance_cents = 99_000
    rm.check(_make_intent())  # no raise


def test_tier2_daily_loss_exceeds_cap_trips(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client(balance_cents=100_000)
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, MAX_DAILY_LOSS_USD=50.0)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    # Drop balance so loss > $50 -> 5001 cents.
    rm._balance_cents = 94_999  # loss = 5001 cents > 5000
    with pytest.raises(KillSwitchActive):
        rm.check(_make_intent())
    assert rm._killed is True
    assert os.path.exists(kill_file)
    row = db.execute("SELECT reason FROM kill_events").fetchone()
    assert row is not None
    assert row[0] == "daily_loss"


# ----------------------------------------------------------------------
# Tier 3 — per-market contract cap
# ----------------------------------------------------------------------


def test_tier3_per_market_within_cap_passes(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, MAX_PER_MARKET_CONTRACTS=100)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm.check(_make_intent(count=50))


def test_tier3_per_market_exceeds_cap_raises_risk_error(
    db: sqlite3.Connection, kill_file: str
) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, MAX_PER_MARKET_CONTRACTS=100)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    # Seed 60 existing open contracts on this ticker (FK requires markets row).
    db.executescript(
        """
        INSERT INTO markets (ticker, event_ticker, series_ticker, category, status,
            tick_size, price_level_structure, close_time_ms,
            first_seen_ms, last_refreshed_ms, raw_json)
        VALUES ('DEMO-MKT-A','EVT-X','SER-X','CAT','open','0.01','standard',0,0,0,'{}');

        INSERT INTO orders (
            client_order_id, ticker, side, action, price_dollars, count,
            time_in_force, post_only, status, created_ts_ms
        ) VALUES ('coid1', 'DEMO-MKT-A', 'yes', 'buy', '0.50', 60,
                  'GTC', 1, 'resting', 1);
        """
    )
    db.commit()
    with pytest.raises(RiskError) as exc:
        rm.check(_make_intent(count=50))
    assert "per-market cap" in str(exc.value)
    # Tier 3 must NOT trip the full kill switch.
    assert rm._killed is False


# ----------------------------------------------------------------------
# Tier 4 — per-event correlated exposure cap
# ----------------------------------------------------------------------


def test_tier4_per_event_within_cap_passes(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client(balance_cents=100_000)
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, MAX_PER_EVENT_PCT=0.10)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    # Seed markets row so the event lookup succeeds.
    db.execute(
        """INSERT INTO markets (
            ticker, event_ticker, series_ticker, category, status,
            tick_size, price_level_structure, close_time_ms,
            first_seen_ms, last_refreshed_ms, raw_json
        ) VALUES ('DEMO-MKT-A','EVT-X','SER-X','CAT','open',
                  '0.01','standard',0,0,0,'{}')"""
    )
    db.commit()
    # Intent of 10 * $0.50 = 500 cents vs cap 10_000 cents. Passes.
    rm.check(_make_intent(count=10, price_dollars=Decimal("0.50")))


def test_tier4_per_event_exceeds_cap_raises_risk_error(
    db: sqlite3.Connection, kill_file: str
) -> None:
    client = _make_client(balance_cents=100_000)
    # Raise per-market cap so tier 3 doesn't fire before tier 4.
    settings = _make_settings(
        KILL_SWITCH_FILE=kill_file,
        MAX_PER_EVENT_PCT=0.10,
        MAX_PER_MARKET_CONTRACTS=10_000,
    )
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    db.executescript(
        """
        INSERT INTO markets (ticker, event_ticker, series_ticker, category, status,
            tick_size, price_level_structure, close_time_ms,
            first_seen_ms, last_refreshed_ms, raw_json)
        VALUES ('DEMO-MKT-A','EVT-X','SER-X','CAT','open','0.01','standard',0,0,0,'{}'),
               ('DEMO-MKT-B','EVT-X','SER-X','CAT','open','0.01','standard',0,0,0,'{}');

        INSERT INTO orders (client_order_id, ticker, side, action, price_dollars,
            count, time_in_force, post_only, status, created_ts_ms)
        VALUES
           ('c1','DEMO-MKT-A','yes','buy','0.80',100,'GTC',1,'resting',1),
           ('c2','DEMO-MKT-B','yes','buy','0.50', 50,'GTC',1,'resting',1);
        """
    )
    db.commit()
    # Existing exposure: 100*80 + 50*50 = 8000 + 2500 = 10500 cents
    # (already over cap of 10_000). New intent only pushes further over.
    with pytest.raises(RiskError) as exc:
        rm.check(_make_intent(count=10, price_dollars=Decimal("0.50")))
    assert "per-event cap" in str(exc.value)
    assert rm._killed is False


def test_tier4_skipped_when_market_row_missing(
    db: sqlite3.Connection, kill_file: str
) -> None:
    client = _make_client(balance_cents=100_000)
    settings = _make_settings(KILL_SWITCH_FILE=kill_file)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    # No markets row for this ticker — tier 4 returns early without error.
    rm.check(_make_intent(count=10))


# ----------------------------------------------------------------------
# Tier 5 — drawdown cap
# ----------------------------------------------------------------------


def test_tier5_drawdown_under_cap_passes(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client(balance_cents=100_000)
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, MAX_DRAWDOWN_PCT=0.05)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm._peak_balance_cents = 100_000
    rm._balance_cents = 97_000  # 3% drawdown, under 5% cap
    rm.check(_make_intent())


def test_tier5_drawdown_exceeds_cap_trips(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client(balance_cents=100_000)
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, MAX_DRAWDOWN_PCT=0.05)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm._peak_balance_cents = 100_000
    rm._balance_cents = 90_000  # 10% drawdown > 5% cap
    # Reset start-of-day so tier 2 doesn't trip first.
    rm._start_of_day_balance_cents = 90_000
    with pytest.raises(KillSwitchActive):
        rm.check(_make_intent())
    assert rm._killed is True
    row = db.execute("SELECT reason FROM kill_events").fetchone()
    assert row is not None
    assert row[0] == "drawdown"


# ----------------------------------------------------------------------
# Tier 6 — dead-man heartbeat
# ----------------------------------------------------------------------


def test_tier6_fresh_heartbeat_passes(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, HEARTBEAT_TIMEOUT_S=60)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    now_ms = int(time.time() * 1000)
    db.execute(
        "INSERT INTO heartbeats (thread_name, ts_ms) VALUES ('main', ?)",
        (now_ms,),
    )
    db.commit()
    rm.check(_make_intent())  # no raise


def test_tier6_stale_heartbeat_trips(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, HEARTBEAT_TIMEOUT_S=60)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    # Heartbeat 10 minutes old.
    old_ms = int(time.time() * 1000) - 10 * 60 * 1000
    db.execute(
        "INSERT INTO heartbeats (thread_name, ts_ms) VALUES ('main', ?)",
        (old_ms,),
    )
    db.commit()
    with pytest.raises(KillSwitchActive):
        rm.check(_make_intent())
    assert rm._killed is True
    row = db.execute("SELECT reason FROM kill_events").fetchone()
    assert row is not None
    assert row[0] == "heartbeat"


def test_tier6_missing_heartbeat_passes(db: sqlite3.Connection, kill_file: str) -> None:
    """Bot just started — no heartbeat row yet. Tier 6 must pass."""
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm.check(_make_intent())  # no raise


# ----------------------------------------------------------------------
# trip() idempotency + kill-file creation
# ----------------------------------------------------------------------


def test_trip_is_idempotent(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm.trip("manual", {"x": 1})
    rm.trip("manual", {"x": 2})  # second call is a no-op
    rows = db.execute("SELECT COUNT(*) FROM kill_events").fetchone()
    assert rows[0] == 1


def test_trip_creates_kill_file(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    assert not os.path.exists(kill_file)
    rm.trip("manual", {"reason": "test"})
    assert os.path.exists(kill_file)
    with open(kill_file) as f:
        assert "manual" in f.read()


def test_trip_calls_executor_cancel_all(db: sqlite3.Connection, kill_file: str) -> None:
    client = _make_client()
    settings = _make_settings(KILL_SWITCH_FILE=kill_file)
    executor = MagicMock()
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm.set_executor(executor)
    rm.trip("manual", {})
    executor.cancel_all.assert_called_once()


# ----------------------------------------------------------------------
# Ordering + refresh behavior
# ----------------------------------------------------------------------


def test_tier1_runs_before_others(db: sqlite3.Connection, kill_file: str) -> None:
    """Kill flag must short-circuit even when other tiers would also trip."""
    client = _make_client(balance_cents=100_000)
    settings = _make_settings(KILL_SWITCH_FILE=kill_file, MAX_DAILY_LOSS_USD=50.0)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm._killed = True
    # Also rig tier 2 to trip — but tier 1 raises first.
    rm._balance_cents = 1
    with pytest.raises(KillSwitchActive) as exc:
        rm.check(_make_intent())
    # In-memory kill flag message (tier 1), not the daily-loss message.
    assert "in-memory" in str(exc.value) or "kill" in str(exc.value).lower()


def test_on_utc_rollover_resets_daily_anchor(
    db: sqlite3.Connection, kill_file: str
) -> None:
    client = _make_client(balance_cents=80_000)
    settings = _make_settings(KILL_SWITCH_FILE=kill_file)
    rm = RiskManager(client=client, settings=settings, db_conn=db)
    rm._balance_cents = 80_000
    rm._start_of_day_balance_cents = 100_000
    rm.on_utc_rollover()
    assert rm._start_of_day_balance_cents == 80_000
