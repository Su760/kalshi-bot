// Right-column panels: P&L over time, signal distribution donut, scans/min sparkline.
const { useMemo: _useMemoP } = React;
const { PnlChart, DonutChart, SparkLine: SparkLine2 } = window.KALSHI_CHARTS;

function PnlPanel({ series }) {
  const last = series[series.length - 1];
  const first = series[0];
  const delta = last - first;
  const pct = (delta / Math.max(1, Math.abs(first || 1))) * 100;
  const up = delta >= 0;
  const dayLabels = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
  // Rotate to end on today (Saturday placeholder, adjust at runtime if needed)
  const today = new Date().getDay(); // 0..6
  const ordered = [];
  for (let i = 6; i >= 0; i--) {
    const d = (today - i + 7) % 7;
    ordered.push(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][d]);
  }
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>P&L · 7 days</h3>
        <div className="panel-meta mono">
          <span className="dim">cur</span>{" "}
          <span style={{ color: up ? "#10B981" : "#EF4444" }}>
            {up ? "+" : "−"}${Math.abs(last).toFixed(2)}
          </span>
          <span className="sep">·</span>
          <span className="dim">7d</span>{" "}
          <span style={{ color: up ? "#10B981" : "#EF4444" }}>
            {up ? "+" : "−"}
            {Math.abs(pct).toFixed(1)}%
          </span>
        </div>
      </div>
      <div className="pnl-chart-wrap">
        <PnlChart data={series} height={196} color="#10B981" />
        <div className="day-axis mono">
          {ordered.map((d, i) => (
            <span key={i} className={i === 6 ? "today" : ""}>
              {d}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function DistributionPanel({ counts }) {
  const total = counts.bracket + counts.thin + counts.other || 1;
  const slices = [
    { name: "bracket_sum_arb", value: counts.bracket, color: "#3B82F6" },
    { name: "thin_spread", value: counts.thin, color: "#10B981" },
    { name: "other", value: counts.other, color: "#F59E0B" },
  ];
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Signal distribution</h3>
        <div className="panel-meta mono">last 24h · n={total}</div>
      </div>
      <div className="donut-row">
        <div className="donut-svg">
          <DonutChart slices={slices} size={172} thickness={18} />
          <div className="donut-center">
            <div className="donut-num mono">{total}</div>
            <div className="donut-sub">signals</div>
          </div>
        </div>
        <div className="donut-legend">
          {slices.map((s) => {
            const pct = (s.value / total) * 100;
            return (
              <div className="legend-row" key={s.name}>
                <span className="legend-dot" style={{ background: s.color }} />
                <span className="legend-name">{s.name}</span>
                <span className="legend-val mono">{s.value}</span>
                <span className="legend-pct mono dim">{pct.toFixed(0)}%</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function ScansPanel({ data }) {
  const cur = data[data.length - 1];
  const avg = data.reduce((a, b) => a + b, 0) / data.length;
  const peak = Math.max(...data);
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Markets scanned · 60m</h3>
        <div className="panel-meta mono">
          <span className="dim">cur</span> {cur}/m
          <span className="sep">·</span>
          <span className="dim">avg</span> {avg.toFixed(0)}/m
          <span className="sep">·</span>
          <span className="dim">peak</span> {peak}/m
        </div>
      </div>
      <div className="scans-chart">
        <SparkLine2
          data={data}
          height={64}
          color="#F5F5F5"
          strokeWidth={1.25}
        />
      </div>
    </div>
  );
}

Object.assign(window, { PnlPanel, DistributionPanel, ScansPanel });
