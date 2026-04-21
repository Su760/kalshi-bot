"""Prometheus metrics registry for the Kalshi trading bot.

All metrics are module-level singletons — import and use directly.
Counters never reset within a process. Gauges reflect current state.
"""
from prometheus_client import Counter, Gauge

# --- WebSocket ---
ws_reconnects_total = Counter(
    "kalshi_ws_reconnects_total",
    "Total WebSocket reconnections since process start",
)
ws_messages_total = Counter(
    "kalshi_ws_messages_total",
    "Total WS messages received",
    ["type"],  # snapshot, delta, trade, subscribed, error, unknown
)

# --- Orders ---
orders_submitted_total = Counter(
    "kalshi_orders_submitted_total",
    "Total orders submitted (paper + live)",
    ["mode"],  # paper, live
)
orders_filled_total = Counter(
    "kalshi_orders_filled_total",
    "Total orders filled",
)
orders_rejected_total = Counter(
    "kalshi_orders_rejected_total",
    "Total orders rejected",
    ["reason"],  # reject code or 'unknown'
)

# --- Risk ---
risk_checks_total = Counter(
    "kalshi_risk_checks_total",
    "Total calls to RiskManager.check()",
)
kill_switch_trips_total = Counter(
    "kalshi_kill_switch_trips_total",
    "Total kill switch trips",
    ["reason"],  # daily_loss, drawdown, heartbeat, etc.
)

# --- Scanner ---
signals_fired_total = Counter(
    "kalshi_signals_fired_total",
    "Total signals returned by any SignalModule",
    ["module", "detector"],
)

# --- P&L ---
balance_dollars = Gauge(
    "kalshi_balance_dollars",
    "Current account balance in dollars",
)
unrealized_pnl_dollars = Gauge(
    "kalshi_unrealized_pnl_dollars",
    "Current unrealized P&L in dollars",
)
open_positions_count = Gauge(
    "kalshi_open_positions_count",
    "Number of currently open positions",
)

# --- Reconciler ---
reconcile_orphans_total = Counter(
    "kalshi_reconcile_orphans_total",
    "Total orphan orders detected by reconciler",
)
reconcile_lost_orders_total = Counter(
    "kalshi_reconcile_lost_orders_total",
    "Total lost orders detected by reconciler",
)

# --- Process health ---
orderbook_snapshots_written_total = Counter(
    "kalshi_orderbook_snapshots_written_total",
    "Total orderbook snapshots written to DB",
)
