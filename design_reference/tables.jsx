// Recent Signals + Active Positions tables.
const { useMemo: _useMemoT } = React;

function fmtTime(ts) {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}
function fmtHeld(ms) {
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h >= 24) {
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h`;
  }
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

function edgeClass(edge) {
  const pct = edge * 100;
  if (pct > 5) return "edge-good";
  if (pct >= 2) return "edge-warn";
  return "edge-flat";
}

function ActionBadge({ action, reason }) {
  const cls =
    action === "FIRED"
      ? "act-fired"
      : action === "BLOCKED"
        ? "act-blocked"
        : "act-skipped";
  return (
    <span className={`act ${cls}`} title={reason || ""}>
      <span className="act-label">{action}</span>
      {reason && <span className="act-reason">{reason}</span>}
    </span>
  );
}

function SignalsTable({ signals }) {
  const rows = signals.slice(0, 20);
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Recent signals</h3>
        <div className="panel-meta mono">
          last 20 · {signals.length} buffered
        </div>
      </div>
      <div className="table-wrap">
        <table className="data-table mono">
          <thead>
            <tr>
              <th className="col-time">TIME</th>
              <th className="col-ticker">TICKER</th>
              <th className="col-det">DETECTOR</th>
              <th className="col-edge num">EDGE</th>
              <th className="col-side">SIDE</th>
              <th className="col-action">ACTION</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={i}
                className={r.action === "FIRED" ? "row-fired" : "row-dim"}
              >
                <td className="col-time dim">{fmtTime(r.ts)}</td>
                <td className="col-ticker">
                  <span className="tk">{r.ticker}</span>
                </td>
                <td className="col-det dim">{r.detector}</td>
                <td className={`col-edge num ${edgeClass(r.edge)}`}>
                  +{(r.edge * 100).toFixed(2)}%
                </td>
                <td
                  className={`col-side ${r.side === "YES" ? "side-yes" : "side-no"}`}
                >
                  {r.side}
                  <span className="dim"> @{r.price.toFixed(2)}</span>
                </td>
                <td className="col-action">
                  <ActionBadge action={r.action} reason={r.reason} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PositionsTable({ positions }) {
  // pre-compute totals
  const totals = positions.reduce(
    (acc, p) => {
      const upnl = (p.current - p.entry) * (p.side === "YES" ? 1 : -1) * p.size;
      acc.upnl += upnl;
      acc.exp += p.entry * p.size;
      return acc;
    },
    { upnl: 0, exp: 0 },
  );

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Active positions</h3>
        <div className="panel-meta mono">
          <span className="dim">unrealized</span>{" "}
          <span style={{ color: totals.upnl >= 0 ? "#10B981" : "#EF4444" }}>
            {totals.upnl >= 0 ? "+" : "−"}${Math.abs(totals.upnl).toFixed(2)}
          </span>
        </div>
      </div>
      <div className="table-wrap">
        <table className="data-table mono">
          <thead>
            <tr>
              <th className="col-ticker">TICKER</th>
              <th className="col-side">SIDE</th>
              <th className="col-size num">SIZE</th>
              <th className="col-price num">ENTRY</th>
              <th className="col-price num">CURRENT</th>
              <th className="col-pnl num">UNREALIZED</th>
              <th className="col-held num">HELD</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => {
              const sign = p.side === "YES" ? 1 : -1;
              const upnl = (p.current - p.entry) * sign * p.size;
              const upnlPct = (((p.current - p.entry) * sign) / p.entry) * 100;
              const cls =
                upnl > 0 ? "pnl-up" : upnl < 0 ? "pnl-dn" : "pnl-flat";
              return (
                <tr key={i}>
                  <td className="col-ticker">
                    <span className="tk">{p.ticker}</span>
                  </td>
                  <td
                    className={`col-side ${p.side === "YES" ? "side-yes" : "side-no"}`}
                  >
                    {p.side}
                  </td>
                  <td className="col-size num dim">{p.size}</td>
                  <td className="col-price num">{p.entry.toFixed(2)}</td>
                  <td className="col-price num">{p.current.toFixed(2)}</td>
                  <td className={`col-pnl num ${cls}`}>
                    {upnl >= 0 ? "+" : "−"}${Math.abs(upnl).toFixed(2)}
                    <span className="pnl-pct">
                      {" "}
                      ({upnlPct >= 0 ? "+" : "−"}
                      {Math.abs(upnlPct).toFixed(1)}%)
                    </span>
                  </td>
                  <td className="col-held num dim">{fmtHeld(p.heldMs)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

Object.assign(window, { SignalsTable, PositionsTable, ActionBadge });
