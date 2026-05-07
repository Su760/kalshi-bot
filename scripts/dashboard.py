"""Local web dashboard for the Kalshi trading bot. Read-only view of data/kalshi.db."""

import sqlite3
import time
from pathlib import Path

from flask import Flask

DB_PATH = Path(__file__).parent.parent / "data" / "kalshi.db"
app = Flask(__name__)


def _conn() -> sqlite3.Connection:
    """Open kalshi.db in read-only WAL mode."""
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(sql, params).fetchall()


def _scalar(sql: str, params: tuple = ()) -> object:
    with _conn() as conn:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None


# ── HTML helpers ──────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'SF Mono', 'Fira Code', monospace; background: #0d1117;
       color: #c9d1d9; padding: 24px; }
h1 { font-size: 1.4rem; color: #58a6ff; margin-bottom: 4px; }
.meta { font-size: 0.75rem; color: #8b949e; margin-bottom: 28px; }
.panel { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
         padding: 20px; margin-bottom: 20px; }
.panel h2 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em;
             color: #8b949e; margin-bottom: 14px; }
.stats { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 6px; }
.stat { background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
        padding: 12px 18px; min-width: 160px; }
.stat .label { font-size: 0.7rem; color: #8b949e; margin-bottom: 4px; }
.stat .value { font-size: 1.25rem; color: #79c0ff; font-weight: 600; }
.pill { display: inline-block; padding: 2px 10px; border-radius: 12px;
        font-size: 0.75rem; font-weight: 600; margin: 2px; }
.pill-open     { background: #1f4068; color: #79c0ff; }
.pill-filled   { background: #1a3a2a; color: #56d364; }
.pill-canceled { background: #3a1f2a; color: #ff7b72; }
.pill-other    { background: #2d2d2d; color: #8b949e; }
table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
th { text-align: left; color: #8b949e; font-weight: 500; padding: 6px 10px;
     border-bottom: 1px solid #30363d; }
td { padding: 6px 10px; border-bottom: 1px solid #21262d; vertical-align: top; }
tr:last-child td { border-bottom: none; }
.side-yes { color: #56d364; }
.side-no  { color: #ff7b72; }
.empty { color: #484f58; font-style: italic; font-size: 0.8rem; }
.pnl-pos { color: #56d364; }
.pnl-neg { color: #ff7b72; }
.age-ok  { color: #56d364; }
.age-warn { color: #e3b341; }
.age-dead { color: #ff7b72; }
"""


def _ms_to_str(ts_ms: int | None) -> str:
    if ts_ms is None:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts_ms / 1000))


def _age_str(ts_ms: int | None) -> tuple[str, str]:
    """Return (age_text, css_class)."""
    if ts_ms is None:
        return "no heartbeat", "age-dead"
    age_s = (time.time() * 1000 - ts_ms) / 1000
    if age_s < 30:
        cls = "age-ok"
    elif age_s < 120:
        cls = "age-warn"
    else:
        cls = "age-dead"
    if age_s < 60:
        label = f"{int(age_s)}s ago"
    elif age_s < 3600:
        label = f"{int(age_s/60)}m ago"
    else:
        label = f"{age_s/3600:.1f}h ago"
    return label, cls


def _pill_class(status: str) -> str:
    return {"open": "pill-open", "filled": "pill-filled",
            "canceled": "pill-canceled"}.get(status.lower(), "pill-other")


def _pnl_class(val: str | None) -> str:
    try:
        return "pnl-pos" if float(val or 0) >= 0 else "pnl-neg"
    except ValueError:
        return ""


# ── Data fetchers ─────────────────────────────────────────────────────────────

def bot_status() -> dict:
    snapshot_count = _scalar("SELECT COUNT(*) FROM orderbook_snapshots") or 0
    active_markets = _scalar("SELECT COUNT(*) FROM markets WHERE status='active'") or 0
    last_snap_ms   = _scalar("SELECT MAX(ts_ms) FROM orderbook_snapshots")
    heartbeats     = _query("SELECT thread_name, ts_ms FROM heartbeats")
    latest_hb_ms   = max((r["ts_ms"] for r in heartbeats), default=None)
    return {
        "snapshot_count": snapshot_count,
        "active_markets": active_markets,
        "last_snap": _ms_to_str(last_snap_ms),
        "heartbeat_age": _age_str(latest_hb_ms),
        "heartbeats": list(heartbeats),
    }


def paper_trading() -> dict:
    total     = _scalar("SELECT COUNT(*) FROM orders") or 0
    by_status = _query("SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status")
    recent    = _query(
        "SELECT ticker, side, price_dollars, count, status, created_ts_ms "
        "FROM orders ORDER BY created_ts_ms DESC LIMIT 10"
    )
    return {"total": total, "by_status": list(by_status), "recent": list(recent)}


def pnl_log() -> dict:
    rows = _query("SELECT * FROM pnl_log ORDER BY date_utc")
    running = 0.0
    enriched = []
    for r in rows:
        try:
            running += float(r["realized_pnl"])
        except (ValueError, TypeError):
            pass
        enriched.append((r, running))
    return {"rows": enriched}


def kill_events() -> list:
    return _query(
        "SELECT id, ts_ms, reason, context_json FROM kill_events ORDER BY ts_ms DESC"
    )


# ── HTML builders ─────────────────────────────────────────────────────────────

def render_bot_status(d: dict) -> str:
    hb_label, hb_cls = d["heartbeat_age"]
    hb_rows = "".join(
        f"<tr><td>{r['thread_name']}</td><td>{_ms_to_str(r['ts_ms'])}</td></tr>"
        for r in d["heartbeats"]
    ) or '<tr><td colspan="2" class="empty">no heartbeats recorded</td></tr>'

    return f"""
<div class="panel">
  <h2>Bot Status</h2>
  <div class="stats">
    <div class="stat"><div class="label">Snapshots</div>
      <div class="value">{d['snapshot_count']:,}</div></div>
    <div class="stat"><div class="label">Active Markets</div>
      <div class="value">{d['active_markets']:,}</div></div>
    <div class="stat"><div class="label">Last Snapshot</div>
      <div class="value" style="font-size:0.85rem">{d['last_snap']}</div></div>
    <div class="stat"><div class="label">Heartbeat Age</div>
      <div class="value {hb_cls}" style="font-size:0.9rem">{hb_label}</div></div>
  </div>
  <table style="margin-top:14px;width:auto">
    <tr><th>Thread</th><th>Last Seen (UTC)</th></tr>
    {hb_rows}
  </table>
</div>
"""


def render_paper_trading(d: dict) -> str:
    pills = "".join(
        f'<span class="pill {_pill_class(r["status"])}">{r["status"]} ({r["cnt"]})</span>'
        for r in d["by_status"]
    ) or '<span class="empty">no orders</span>'

    order_rows = "".join(
        f"""<tr>
          <td>{r['ticker']}</td>
          <td class="{'side-yes' if r['side'] == 'yes' else 'side-no'}">{r['side'].upper()}</td>
          <td>{r['price_dollars']}</td>
          <td>{r['count']}</td>
          <td><span class="pill {_pill_class(r['status'])}">{r['status']}</span></td>
          <td style="color:#8b949e">{_ms_to_str(r['created_ts_ms'])}</td>
        </tr>"""
        for r in d["recent"]
    ) or '<tr><td colspan="6" class="empty">no orders yet</td></tr>'

    return f"""
<div class="panel">
  <h2>Paper Trading</h2>
  <div class="stats">
    <div class="stat"><div class="label">Total Orders</div>
      <div class="value">{d['total']:,}</div></div>
  </div>
  <div style="margin:12px 0">{pills}</div>
  <table>
    <tr>
      <th>Ticker</th><th>Side</th><th>Price</th>
      <th>Contracts</th><th>Status</th><th>Time (UTC)</th>
    </tr>
    {order_rows}
  </table>
</div>
"""


def render_pnl(d: dict) -> str:
    rows_html = ""
    for row, running in d["rows"]:
        rtd   = f'<td class="{_pnl_class(row["realized_pnl"])}">{row["realized_pnl"]}</td>'
        urtd  = f'<td class="{_pnl_class(row["unrealized_pnl"])}">{row["unrealized_pnl"]}</td>'
        runtd = f'<td class="{_pnl_class(str(running))}">{running:.4f}</td>'
        rows_html += (
            f"<tr><td>{row['date_utc']}</td>"
            f"<td>{row['opening_balance']}</td><td>{row['closing_balance']}</td>"
            f"{rtd}{urtd}<td>{row['fees_paid']}</td>"
            f"<td>{row['trade_count']}</td><td>{row['win_count']}</td>"
            f"<td>{row['kill_events']}</td>{runtd}</tr>"
        )

    if not rows_html:
        rows_html = '<tr><td colspan="10" class="empty">no P&amp;L records yet</td></tr>'

    return f"""
<div class="panel">
  <h2>P&amp;L Log</h2>
  <table>
    <tr>
      <th>Date</th><th>Open Bal</th><th>Close Bal</th>
      <th>Realized</th><th>Unrealized</th><th>Fees</th>
      <th>Trades</th><th>Wins</th><th>Kill Evts</th><th>Running Total</th>
    </tr>
    {rows_html}
  </table>
</div>
"""


def render_kill_events(rows: list) -> str:
    rows_html = "".join(
        f"<tr><td>{r['id']}</td><td>{_ms_to_str(r['ts_ms'])}</td>"
        f"<td style='color:#ff7b72'>{r['reason']}</td>"
        f"<td style='color:#8b949e;font-size:0.72rem'>{r['context_json']}</td></tr>"
        for r in rows
    ) or '<tr><td colspan="4" class="empty">no kill events — good</td></tr>'

    return f"""
<div class="panel">
  <h2>Kill Events</h2>
  <table>
    <tr><th>#</th><th>Time (UTC)</th><th>Reason</th><th>Context</th></tr>
    {rows_html}
  </table>
</div>
"""


# ── Route ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index() -> str:
    now     = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    status  = bot_status()
    trading = paper_trading()
    pnl     = pnl_log()
    kills   = kill_events()

    body = (
        render_bot_status(status)
        + render_paper_trading(trading)
        + render_pnl(pnl)
        + render_kill_events(kills)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="10">
  <title>Kalshi Bot Dashboard</title>
  <style>{CSS}</style>
</head>
<body>
  <h1>Kalshi Bot Dashboard</h1>
  <p class="meta">Last updated: {now} &nbsp;&middot;&nbsp; Auto-refreshes every 10 seconds</p>
  {body}
</body>
</html>"""


if __name__ == "__main__":
    print(f"Dashboard → http://localhost:5050  (DB: {DB_PATH})")
    app.run(host="0.0.0.0", port=5050, debug=False)
