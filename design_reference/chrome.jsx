// Top bar + KPI strip + footer presentational pieces.
const { useState, useEffect, useMemo, useRef } = React;
const { SparkBars, SparkLine } = window.KALSHI_CHARTS;

function fmtUptime(ms) {
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${d}d ${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m`;
}
function fmtAgo(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s ago`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m ago`;
}
function fmtMoney(n, signed = true) {
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  const abs = Math.abs(n);
  const s =
    abs >= 1000
      ? abs.toLocaleString("en-US", {
          maximumFractionDigits: 2,
          minimumFractionDigits: 2,
        })
      : abs.toFixed(2);
  return `${signed ? sign : n < 0 ? "−" : ""}$${s}`;
}
function fmtPct(n, digits = 2) {
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toFixed(digits)}%`;
}

function TopBar({ status, uptimeMs, lastScanAgo, mode, onModeRequest }) {
  const live = status === "LIVE";
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className={`status-dot ${live ? "live" : "paper"}`}>
          <span className="dot" />
          <span className="status-label">{live ? "LIVE" : "PAPER MODE"}</span>
        </div>
        <div className="topbar-meta">
          <span className="meta-label">UPTIME</span>
          <span className="meta-value mono">
            Running for {fmtUptime(uptimeMs)}
          </span>
        </div>
        <div className="topbar-meta">
          <span className="meta-label">LAST SCAN</span>
          <span className="meta-value mono">{lastScanAgo}</span>
        </div>
      </div>
      <div className="topbar-right">
        <div className="mode-toggle" data-mode={mode}>
          <button
            className={mode === "PAPER" ? "active" : ""}
            onClick={() => onModeRequest("PAPER")}
          >
            PAPER
          </button>
          <button
            className={mode === "LIVE" ? "active" : ""}
            onClick={() => onModeRequest("LIVE")}
            title="Locked — requires auth approval"
          >
            LIVE <span className="lock">🔒</span>
          </button>
        </div>
      </div>
    </header>
  );
}

function KpiCard({ label, value, sub, valueColor, children }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-row">
        <div className="kpi-value mono" style={{ color: valueColor }}>
          {value}
        </div>
        {children && <div className="kpi-aux">{children}</div>}
      </div>
      {sub && <div className="kpi-sub mono">{sub}</div>}
    </div>
  );
}

function KpiStrip({
  pnl,
  pnlPct,
  signalsToday,
  signals24h,
  openPositions,
  exposure,
  winRate,
  winSample,
}) {
  const pnlColor = pnl >= 0 ? "#10B981" : "#EF4444";
  return (
    <section className="kpi-strip">
      <KpiCard
        label="TOTAL P&L"
        value={fmtMoney(pnl)}
        valueColor={pnlColor}
        sub={
          <span style={{ color: pnlColor }}>
            {fmtPct(pnlPct)} <span className="dim">since deploy</span>
          </span>
        }
      />
      <KpiCard
        label="SIGNALS FIRED · 24H"
        value={signalsToday}
        sub={
          <span className="dim">
            peak {Math.max(...signals24h)}/hr · avg{" "}
            {(
              signals24h.reduce((a, b) => a + b, 0) / signals24h.length
            ).toFixed(1)}
            /hr
          </span>
        }
      >
        <div className="spark-wrap">
          <SparkBars data={signals24h} height={36} color="#3B82F6" />
        </div>
      </KpiCard>
      <KpiCard
        label="OPEN POSITIONS"
        value={openPositions}
        sub={
          <span className="dim">
            total exposure{" "}
            <span className="mono fg">{fmtMoney(exposure, false)}</span>
          </span>
        }
      />
      <KpiCard
        label="WIN RATE"
        value={`${winRate.toFixed(1)}%`}
        sub={<span className="dim">n={winSample} · last 30d</span>}
      >
        <div className="winrate-bar">
          <div className="winrate-fill" style={{ width: `${winRate}%` }} />
        </div>
      </KpiCard>
    </section>
  );
}

function Footer({ build, sha, dbBytes, logBytes, scanRate }) {
  const fmtBytes = (n) =>
    n > 1e9
      ? `${(n / 1e9).toFixed(2)} GB`
      : n > 1e6
        ? `${(n / 1e6).toFixed(1)} MB`
        : `${(n / 1e3).toFixed(0)} KB`;
  return (
    <footer className="footer">
      <div className="foot-left">
        <span className="foot-item">
          <span className="dim">build</span>{" "}
          <span className="mono">{build}</span>
        </span>
        <span className="foot-item">
          <span className="dim">sha</span> <span className="mono">{sha}</span>
        </span>
        <span className="foot-item">
          <span className="dim">db</span>{" "}
          <span className="mono">{fmtBytes(dbBytes)}</span>
        </span>
        <span className="foot-item">
          <span className="dim">log</span>{" "}
          <span className="mono">{fmtBytes(logBytes)}</span>
        </span>
      </div>
      <div className="foot-right">
        <span className="foot-item">
          <span className="dim">scan rate</span>{" "}
          <span className="mono">{scanRate.toFixed(1)}/s</span>
        </span>
        <span className="foot-item">
          <span className="dim">env</span>{" "}
          <span className="mono">demo-api.kalshi.co</span>
        </span>
      </div>
    </footer>
  );
}

Object.assign(window, {
  TopBar,
  KpiStrip,
  Footer,
  fmtUptime,
  fmtAgo,
  fmtMoney,
  fmtPct,
});
