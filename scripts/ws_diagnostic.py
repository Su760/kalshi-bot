#!/usr/bin/env python3
"""
Standalone WS diagnostic script.

Connects to Kalshi demo WS with real auth, subscribes to a handful of
tickers from the DB, and prints every raw message for 45 seconds.
Also does a manual INSERT into orderbook_snapshots to confirm the DB
write path works at all.

Run from repo root:
  .venv/bin/python scripts/ws_diagnostic.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Make sure repo root is on the path so src.* imports work.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.chdir(ROOT)  # settings load .env from cwd

from src.config.settings import get_settings
from src.core.auth import build_headers, load_private_key
from src.storage.db import get_db

settings = get_settings()
assert settings.kalshi_private_key_path is not None, "kalshi_private_key_path must be set"
private_key = load_private_key(settings.kalshi_private_key_path)

DB_PATH = settings.DB_PATH

# ── Step 0: check DB state ────────────────────────────────────────────────────
conn = get_db(DB_PATH)
rows = conn.execute("SELECT status, COUNT(*) n FROM markets GROUP BY status").fetchall()
print("=== DB market status distribution ===")
for r in rows:
    print(f"  status={r[0]}  count={r[1]}")

# Get 5 active tickers to subscribe to
active_tickers = [
    r[0]
    for r in conn.execute(
        "SELECT ticker FROM markets WHERE status='active' "
        "ORDER BY ROWID LIMIT 5"
    ).fetchall()
]
print(f"\nSubscribing to {len(active_tickers)} tickers: {active_tickers}")

# ── Step 1: manual INSERT to prove DB write works ─────────────────────────────
print("\n=== Testing manual INSERT into orderbook_snapshots ===")
try:
    now_ms = int(time.time() * 1000)
    test_ticker = active_tickers[0] if active_tickers else "TEST"
    conn.execute(
        "INSERT INTO orderbook_snapshots "
        "(ticker, ts_ms, seq, yes_bids_json, no_bids_json, "
        " best_yes_bid, best_no_bid, yes_ask_impl, no_ask_impl, "
        " mid_yes, spread_cents, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            test_ticker,
            now_ms,
            0,
            "[]",
            "[]",
            None,
            None,
            None,
            None,
            None,
            None,
            "diagnostic",
        ),
    )
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) FROM orderbook_snapshots"
    ).fetchone()[0]
    print(f"  ✓ Manual INSERT succeeded. orderbook_snapshots COUNT={count}")
except Exception as e:
    print(f"  ✗ Manual INSERT FAILED: {e}")

# ── Step 2: Connect WS and log raw messages ───────────────────────────────────
from websockets.asyncio.client import connect

TIMEOUT_S = 45
msg_count = 0
type_counts: dict[str, int] = {}


async def run_diagnostic() -> None:
    global msg_count
    assert settings.kalshi_api_key_id is not None, "kalshi_api_key_id must be set"
    headers = build_headers(
        key_id=settings.kalshi_api_key_id,
        private_key=private_key,
        method="GET",
        path_or_url=settings.kalshi_ws_url,
    )

    print(f"\n=== Connecting to {settings.kalshi_ws_url} ===")
    async with connect(
        settings.kalshi_ws_url,
        additional_headers=headers,
        ping_interval=15,
        ping_timeout=10,
        max_size=2**22,
    ) as ws:
        print("  ✓ Connected")

        # Subscribe to orderbook_delta for our tickers
        payload = {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": active_tickers,
            },
        }
        await ws.send(json.dumps(payload))
        print(f"  ✓ Sent subscribe for {active_tickers}")

        deadline = asyncio.get_event_loop().time() + TIMEOUT_S
        async for raw in ws:
            try:
                parsed = json.loads(raw)
            except Exception:
                print(f"  [RAW non-JSON] {str(raw)[:300]}")
                continue

            mtype = parsed.get("type", "UNKNOWN")
            type_counts[mtype] = type_counts.get(mtype, 0) + 1
            msg_count += 1

            # Print first 20 messages in full, then just counts
            if msg_count <= 20:
                print(f"\n  [MSG #{msg_count}] type={mtype}")
                print(f"    keys at top level: {list(parsed.keys())}")
                msg_body = parsed.get("msg", {})
                if isinstance(msg_body, dict):
                    print(f"    msg keys: {list(msg_body.keys())}")
                    # For snapshot/delta show sizes
                    if mtype in ("orderbook_snapshot", "orderbook_delta"):
                        print(f"    market_ticker={msg_body.get('market_ticker') or msg_body.get('ticker')}")
                        print(f"    seq={msg_body.get('seq')}")
                        yes = msg_body.get("yes", [])
                        no = msg_body.get("no", [])
                        print(f"    yes levels={len(yes)}  no levels={len(no)}")
                        if yes:
                            print(f"    yes[0]={yes[0]}  (format check)")
                        if no:
                            print(f"    no[0]={no[0]}")
                else:
                    print(f"    msg (non-dict): {str(msg_body)[:200]}")
            elif msg_count % 50 == 0:
                elapsed = TIMEOUT_S - (deadline - asyncio.get_event_loop().time())
                print(f"  [{elapsed:.0f}s] total={msg_count} types={type_counts}")

            if asyncio.get_event_loop().time() >= deadline:
                break

    print(f"\n=== Done after {TIMEOUT_S}s ===")
    print(f"Total messages: {msg_count}")
    print(f"By type: {type_counts}")

    # Check final count
    final_count = conn.execute(
        "SELECT COUNT(*) FROM orderbook_snapshots"
    ).fetchone()[0]
    print(f"\norderbook_snapshots COUNT = {final_count}")


asyncio.run(run_diagnostic())
conn.close()
