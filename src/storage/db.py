"""SQLite connection helpers for the Kalshi trading bot."""
from __future__ import annotations

import os
import sqlite3


def get_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def apply_schema(conn: sqlite3.Connection, schema_path: str) -> None:
    with open(schema_path) as f:
        conn.executescript(f.read())


def get_default_db() -> sqlite3.Connection:
    # Read DB_PATH directly from env so this works without full Kalshi credentials.
    # When the full bot runs, Settings will also set DB_PATH via the env.
    path = os.environ.get("DB_PATH", "./data/kalshi.db")
    return get_db(path)
