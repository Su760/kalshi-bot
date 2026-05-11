"""Kalshi Bot — Streamlit dashboard, Round 1: page shell + status bar."""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Kalshi Bot",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Design system CSS ─────────────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap');

html, body, .stApp {
    background-color: #0E0E10 !important;
    color: #F5F5F5 !important;
    font-family: 'Inter', sans-serif;
}

/* Hide default Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }

.panel {
    background: #18181B;
    border: 1px solid #2A2A2E;
    border-radius: 6px;
    padding: 16px;
}

code, .mono {
    font-family: 'JetBrains Mono', monospace;
    font-feature-settings: 'tnum';
}

.status-green { color: #10B981; font-weight: 600; }
.status-amber { color: #F59E0B; font-weight: 600; }
.status-red   { color: #EF4444; font-weight: 600; }

.badge-paper {
    background: #1c1f2e;
    color: #F59E0B;
    border: 1px solid #F59E0B;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 12px;
    font-family: 'JetBrains Mono', monospace;
}

@keyframes pulse {
    0%   { opacity: 1; }
    50%  { opacity: 0.4; }
    100% { opacity: 1; }
}
.dot-live {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #10B981;
    animation: pulse 2s infinite;
    margin-right: 6px;
    vertical-align: middle;
}
.dot-warn {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #F59E0B;
    animation: pulse 1s infinite;
    margin-right: 6px;
    vertical-align: middle;
}

.stat-label {
    font-size: 11px;
    color: #6B7280;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
}
.stat-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    font-feature-settings: 'tnum';
}
</style>
""",
    unsafe_allow_html=True,
)

# ── Constants ─────────────────────────────────────────────────────────────────
LOG_FILE = os.path.expanduser("~/Desktop/bot_paper_run.log")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _parse_ts(line: str) -> datetime | None:
    """Return UTC datetime from the first ISO-8601 timestamp found in *line*."""
    m = _TS_RE.search(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(), "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _age_str(ts: datetime) -> str:
    delta = (datetime.now(timezone.utc) - ts).total_seconds()
    if delta < 60:
        return f"{int(delta)}s ago"
    return f"{int(delta // 60)}m ago"


@st.cache_data(ttl=5)
def _read_log_tail(n: int = 200) -> list[str]:
    """Return the last *n* ANSI-stripped lines of the log file."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return [_strip_ansi(ln) for ln in lines[-n:]]
    except OSError:
        return []


def _bot_status(lines: list[str]) -> tuple[str, str]:
    """Return (html_snippet, css_class) based on recency of the last log line."""
    for line in reversed(lines):
        ts = _parse_ts(line)
        if ts is None:
            continue
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age < 30:
            return (
                '<span class="dot-live"></span>'
                '<span class="status-green">PAPER MODE LIVE</span>',
                "green",
            )
        if age < 300:
            return (
                '<span class="dot-warn"></span>'
                '<span class="status-amber">⚠ LAGGING</span>',
                "amber",
            )
        break
    return '<span class="status-red">✗ DOWN</span>', "red"


def _last_scan(lines: list[str]) -> tuple[str, str]:
    """Return (last_scan_ago, stats_str) from the most recent scan_cycle_end line."""
    for line in reversed(lines):
        if "scan_cycle_end" not in line:
            continue
        ts = _parse_ts(line)
        ago = _age_str(ts) if ts else "?"

        dur_m = re.search(r"duration_ms=(\d+)", line)
        sig_m = re.search(r"signals_generated=(\d+)", line)
        dur = dur_m.group(1) if dur_m else "?"
        sig = sig_m.group(1) if sig_m else "?"
        stats = f"{dur}ms | {sig} signal{'s' if sig != '1' else ''}"
        return ago, stats
    return "—", "—"


# ── Refresh button (top-right) ────────────────────────────────────────────────
_hdr_l, _hdr_r = st.columns([8, 1])
with _hdr_r:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# ── Load log data ─────────────────────────────────────────────────────────────
log_lines = _read_log_tail()

# ── Top status bar ────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)

status_html, _status_cls = _bot_status(log_lines)
last_scan_ago, scan_stats = _last_scan(log_lines)

with c1:
    st.markdown(
        f"""
<div class="panel">
  <div class="stat-label">Bot Status</div>
  <div class="stat-value">{status_html}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with c2:
    st.markdown(
        f"""
<div class="panel">
  <div class="stat-label">Last Scan</div>
  <div class="stat-value mono">{last_scan_ago}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with c3:
    st.markdown(
        f"""
<div class="panel">
  <div class="stat-label">Scan Stats</div>
  <div class="stat-value mono">{scan_stats}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with c4:
    st.markdown(
        """
<div class="panel" style="text-align:center; padding-top:20px;">
  <span class="badge-paper">🔒 PAPER MODE</span>
</div>
""",
        unsafe_allow_html=True,
    )

# ── Round 2: KPI strip + main grid ───────────────────────────────────────────
DB_PATH = "data/kalshi.db"

# ── DB helpers ────────────────────────────────────────────────────────────────


def _db_connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


@st.cache_data(ttl=10)
def _db_total_orders() -> int:
    try:
        with _db_connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    except Exception:
        return 0


@st.cache_data(ttl=10)
def _db_unique_tickers() -> int:
    try:
        with _db_connect() as conn:
            return conn.execute("SELECT COUNT(DISTINCT ticker) FROM orders").fetchone()[0]
    except Exception:
        return 0


@st.cache_data(ttl=10)
def _db_orders_24h() -> int:
    try:
        with _db_connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM orders "
                "WHERE created_ts_ms > (strftime('%s','now')*1000 - 86400000)"
            ).fetchone()[0]
    except Exception:
        return 0


@st.cache_data(ttl=10)
def _db_last_order_ms() -> int | None:
    try:
        with _db_connect() as conn:
            row = conn.execute("SELECT MAX(created_ts_ms) FROM orders").fetchone()
            return row[0] if row else None
    except Exception:
        return None


@st.cache_data(ttl=10)
def _db_recent_orders() -> pd.DataFrame:
    try:
        with _db_connect() as conn:
            df = pd.read_sql_query(
                "SELECT ticker, side, action, price_dollars, count, status, created_ts_ms "
                "FROM orders ORDER BY created_ts_ms DESC LIMIT 20",
                conn,
            )
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=10)
def _db_orders_by_hour() -> pd.DataFrame:
    try:
        with _db_connect() as conn:
            df = pd.read_sql_query(
                "SELECT strftime('%H:00', datetime(created_ts_ms/1000,'unixepoch','localtime')) as hr, "
                "COUNT(*) as n FROM orders GROUP BY hr ORDER BY hr",
                conn,
            )
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=10)
def _db_snapshot_count() -> int:
    try:
        with _db_connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0]
    except Exception:
        return 0


@st.cache_data(ttl=10)
def _db_active_markets() -> int:
    try:
        with _db_connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM markets WHERE status='active'"
            ).fetchone()[0]
    except Exception:
        return 0


def _ms_age_str(ts_ms: int | None) -> str:
    """Convert epoch-ms timestamp to human age string (seconds/minutes/hours)."""
    if ts_ms is None:
        return "No orders yet"
    ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    delta = (datetime.now(timezone.utc) - ts).total_seconds()
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    return f"{int(delta // 3600)}h ago"


# ── Section 1: Hero KPIs ──────────────────────────────────────────────────────
st.markdown("---")

kpi1, kpi2, kpi3, kpi4 = st.columns(4)

with kpi1:
    st.markdown(
        f"""
<div class="panel">
  <div class="stat-label">Total Orders</div>
  <div class="stat-value mono">{_db_total_orders()}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with kpi2:
    st.markdown(
        f"""
<div class="panel">
  <div class="stat-label">Unique Tickers</div>
  <div class="stat-value mono">{_db_unique_tickers()}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with kpi3:
    st.markdown(
        f"""
<div class="panel">
  <div class="stat-label">Orders (24h)</div>
  <div class="stat-value mono">{_db_orders_24h()}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with kpi4:
    st.markdown(
        f"""
<div class="panel">
  <div class="stat-label">Last Order</div>
  <div class="stat-value mono">{_ms_age_str(_db_last_order_ms())}</div>
</div>
""",
        unsafe_allow_html=True,
    )


# ── Section 2: Main grid ──────────────────────────────────────────────────────
_left, _right = st.columns([3, 2])

with _left:
    # ── Recent Orders ──────────────────────────────────────────────────────
    st.markdown("#### Recent Orders")
    _orders_raw = _db_recent_orders()
    if _orders_raw.empty:
        st.info("No orders yet")
    else:
        _orders = _orders_raw.copy()
        _orders["Time"] = (
            pd.to_datetime(_orders["created_ts_ms"], unit="ms", utc=True)
            .dt.tz_convert("America/Chicago")
            .dt.strftime("%H:%M:%S")
        )
        _orders["Ticker"] = _orders["ticker"].apply(
            lambda t: t[:28] + "…" if len(str(t)) > 28 else t
        )
        _orders["Side"] = _orders["side"].str.upper()
        _orders["Price"] = (_orders["price_dollars"].astype(float) * 100).round().astype(int).astype(str) + "¢"
        _orders["Qty"] = _orders["count"]
        _orders["Status"] = _orders["status"]
        st.dataframe(
            _orders[["Time", "Ticker", "Side", "Price", "Qty", "Status"]],
            use_container_width=True,
            hide_index=True,
        )

    # ── Scanner Activity ───────────────────────────────────────────────────
    st.markdown("#### Scanner Activity")
    _scan_rows: list[dict] = []
    for _ln in reversed(log_lines):
        if "scan_cycle_end" not in _ln:
            continue
        _ts = _parse_ts(_ln)
        _dur_m = re.search(r"duration_ms=(\d+)", _ln)
        _sig_m = re.search(r"signals_generated=(\d+)", _ln)
        _scan_rows.append(
            {
                "Time": _age_str(_ts) if _ts else "?",
                "Duration": f"{_dur_m.group(1)}ms" if _dur_m else "?",
                "Signals": int(_sig_m.group(1)) if _sig_m else 0,
            }
        )
        if len(_scan_rows) >= 10:
            break

    if not _scan_rows:
        st.info("No scan data")
    else:
        st.dataframe(
            pd.DataFrame(_scan_rows),
            use_container_width=True,
            hide_index=True,
        )

with _right:
    # ── Orders / Hour ──────────────────────────────────────────────────────
    st.markdown("#### Orders / Hour")
    _hourly = _db_orders_by_hour()
    if _hourly.empty:
        st.info("No order history yet")
    else:
        st.bar_chart(_hourly.set_index("hr"))

    # ── DB Stats ───────────────────────────────────────────────────────────
    st.markdown("#### DB Stats")

    def _file_size(path: str) -> str:
        try:
            return f"{os.path.getsize(path) / 1_048_576:.1f}MB"
        except OSError:
            return "?"

    _ds1, _ds2 = st.columns(2)
    with _ds1:
        st.metric("Snapshots", _db_snapshot_count())
        st.metric("Log size", _file_size(os.path.expanduser("~/Desktop/bot_paper_run.log")))
    with _ds2:
        st.metric("Active Markets", _db_active_markets())
        st.metric("DB size", _file_size(DB_PATH))

# ── Footer ────────────────────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False, timeout=2,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


st.markdown("---")
_now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
st.markdown(
    f"""
<div style="text-align: center; color: #6B7280; font-size: 11px;
            font-family: 'JetBrains Mono', monospace; padding: 16px 0;">
  build {_git_sha()} · DB: {DB_PATH} · refreshed {_now}
</div>
""",
    unsafe_allow_html=True,
)
