#!/usr/bin/env python3
"""Diagnose why scanner.predict() never fires a signal.

Run from repo root:
  .venv/bin/python scripts/scan_diagnostic.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

db = sqlite3.connect("data/kalshi.db")
db.row_factory = sqlite3.Row

print("=" * 70)
print("SCAN DIAGNOSTIC — tracing why 0 orders are placed")
print("=" * 70)

# 1) Status filter
total = db.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
active = db.execute("SELECT COUNT(*) FROM markets WHERE status IN ('active','open')").fetchone()[0]
print(f"\n1. Markets total={total}  active/open={active}")

# 2) How many are subscribed (have a live book)?
# We approximate by checking which tickers appear in orderbook_snapshots
with_snaps = db.execute(
    "SELECT COUNT(DISTINCT ticker) FROM orderbook_snapshots"
).fetchone()[0]
print(f"2. Tickers with at least 1 snapshot in DB: {with_snaps}")

# 3) The applies_to gate
from src.core.scanner import MIN_EDGE_PCT, MIN_NET_EDGE_PCT, MIN_OPEN_INTEREST, MIN_VOLUME_24H

print(f"\n3. Scanner applies_to filters:")
print(f"   MIN_VOLUME_24H = {MIN_VOLUME_24H}")
print(f"   MIN_OPEN_INTEREST = {MIN_OPEN_INTEREST}")
print(f"   MIN_EDGE_PCT = {MIN_EDGE_PCT}")
print(f"   MIN_NET_EDGE_PCT = {MIN_NET_EDGE_PCT}")

# Simulate applies_to on all active markets
rows = db.execute(
    "SELECT ticker, status, volume_24h, open_interest, event_ticker, category "
    "FROM markets WHERE status IN ('active','open')"
).fetchall()

pass_status = 0
pass_volume = 0
pass_oi = 0
status_open_count = 0

for r in rows:
    # The code checks market.status == "open" — but DB has "active"!
    if r["status"] == "open":
        status_open_count += 1
    vol = r["volume_24h"] or 0
    oi = r["open_interest"] or 0
    if vol >= MIN_VOLUME_24H:
        pass_volume += 1
    if oi >= MIN_OPEN_INTEREST:
        pass_oi += 1
    if r["status"] == "open" and vol >= MIN_VOLUME_24H and oi >= MIN_OPEN_INTEREST:
        pass_status += 1

print(f"\n4. applies_to breakdown for {len(rows)} active/open markets:")
print(f"   status=='open': {status_open_count}  ← Scanner.applies_to checks status=='open'!")
print(f"   status=='active': {len(rows) - status_open_count}")
print(f"   volume_24h >= {MIN_VOLUME_24H}: {pass_volume}")
print(f"   open_interest >= {MIN_OPEN_INTEREST}: {pass_oi}")
print(f"   ALL THREE pass: {pass_status}")

# 5) Check market status values
print(f"\n5. Distinct status values in markets table:")
for r in db.execute("SELECT status, COUNT(*) n FROM markets GROUP BY status").fetchall():
    print(f"   '{r['status']}' → {r['n']}")

# 6) Check volume/OI distribution
for col in ("volume_24h", "open_interest"):
    stats = db.execute(f"""
        SELECT 
            MIN({col}) as mn, MAX({col}) as mx, AVG({col}) as avg,
            SUM(CASE WHEN {col} > 0 THEN 1 ELSE 0 END) as nonzero
        FROM markets WHERE status IN ('active','open')
    """).fetchone()
    print(f"\n6. {col}: min={stats['mn']}  max={stats['mx']}  avg={stats['avg']:.1f}  nonzero={stats['nonzero']}/{len(rows)}")

# 7) Check bracket arb conditions 
print(f"\n7. Bracket arb: markets per event (need >=2 with live books)")
event_counts = db.execute("""
    SELECT event_ticker, COUNT(*) n
    FROM markets WHERE status IN ('active','open')
    GROUP BY event_ticker
    HAVING COUNT(*) >= 2
    ORDER BY n DESC
    LIMIT 5
""").fetchall()
for r in event_counts:
    print(f"   {r['event_ticker']}: {r['n']} markets")

# 8) Category medians — empty means thin-spread detector always returns None
print(f"\n8. category_medians is passed as empty dict → detect_thin_spread always returns None at line 108-109")

# 9) CRITICAL: the status mismatch
print(f"\n" + "=" * 70)
print("ROOT CAUSE SUMMARY")
print("=" * 70)
print(f"""
BUG #1 (FATAL): scanner.py line 63: `market.status == "open"`
  But ALL markets in DB have status='active' (Kalshi API uses 'active').
  Result: applies_to() returns False for EVERY market → 0 signals.

BUG #2: open_interest=0 for ALL markets, MIN_OPEN_INTEREST=50.
  Even if status were fixed, every market fails this check too.

BUG #3: category_medians is always empty dict.
  detect_thin_spread checks `if category_median_spread_cents <= 0: return None`
  → thin-spread detector is permanently disabled.

BUG #4: bracket_sum_arb needs >=2 markets per event WITH live books.
  Only 200 tickers are subscribed, spread across many events.
  Very few events will have 2+ live books.

COMBINED: Every signal path is dead. No signals → no orders.
""")

db.close()
