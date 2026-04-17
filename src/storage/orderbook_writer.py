"""Persistence helpers for orderbook snapshots and trades.

Separated from `db.py` so the connection helper stays minimal and
table-specific SQL lives next to the schema it mirrors.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from src.core.types import Trade

_SNAPSHOT_COLUMNS = (
    "ticker",
    "ts_ms",
    "seq",
    "yes_bids_json",
    "no_bids_json",
    "best_yes_bid",
    "best_no_bid",
    "yes_ask_impl",
    "no_ask_impl",
    "mid_yes",
    "spread_cents",
    "source",
)

_SNAPSHOT_INSERT_SQL = (
    f"INSERT INTO orderbook_snapshots ({', '.join(_SNAPSHOT_COLUMNS)}) "
    f"VALUES ({', '.join(['?'] * len(_SNAPSHOT_COLUMNS))})"
)


def insert_orderbook_snapshots(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
) -> None:
    """Batch-insert orderbook snapshot rows. Each row must contain the
    columns in `_SNAPSHOT_COLUMNS`. Commits on success.
    """
    if not rows:
        return
    payload = [tuple(r[c] for c in _SNAPSHOT_COLUMNS) for r in rows]
    conn.executemany(_SNAPSHOT_INSERT_SQL, payload)
    conn.commit()


def insert_trade(conn: sqlite3.Connection, t: Trade) -> None:
    """Insert a trade row. `INSERT OR IGNORE` keeps replays on reconnect idempotent."""
    conn.execute(
        "INSERT OR IGNORE INTO trades "
        "(trade_id, ticker, ts_ms, side, action, yes_price, count, is_our_fill) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            t.trade_id,
            t.ticker,
            t.ts_ms,
            t.side,
            t.action,
            t.yes_price,
            t.count,
            1 if t.is_our_fill else 0,
        ),
    )
    conn.commit()
