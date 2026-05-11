// Charts and visualizations for the dashboard.
// All use SVG, no libraries. Flat aesthetic — no gradients/shadows.

const { useMemo } = React;

// ----- Line chart (P&L over time) ---------------------------------
function PnlChart({ data, height = 220, color = "#10B981", showZero = true }) {
  return useMemo(() => {
    if (!data || data.length === 0) return null;
    const W = 1000;
    const H = height;
    const PAD_X = 8;
    const PAD_Y = 18;
    const min = Math.min(0, ...data);
    const max = Math.max(0, ...data);
    const range = max - min || 1;
    const xs = (i) => PAD_X + (i / (data.length - 1)) * (W - PAD_X * 2);
    const ys = (v) => PAD_Y + (1 - (v - min) / range) * (H - PAD_Y * 2);
    const pts = data.map((v, i) => `${xs(i).toFixed(1)},${ys(v).toFixed(1)}`);
    const linePath = `M ${pts.join(" L ")}`;
    const areaPath = `${linePath} L ${xs(data.length - 1).toFixed(1)},${ys(min)} L ${xs(0).toFixed(1)},${ys(min)} Z`;
    const last = data[data.length - 1];
    const isUp = last >= 0;
    const stroke = isUp ? color : "#EF4444";
    // Day boundaries: 7 days, 24 pts each
    const dayMarkers = [];
    const ptsPerDay = data.length / 7;
    for (let d = 1; d < 7; d++) {
      const x = xs(Math.round(d * ptsPerDay));
      dayMarkers.push(x);
    }
    const zeroY = ys(0);

    return (
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="pnl-chart"
        style={{ width: "100%", height: H }}
      >
        {/* day boundary verticals */}
        {dayMarkers.map((x, i) => (
          <line
            key={i}
            x1={x}
            x2={x}
            y1={PAD_Y}
            y2={H - PAD_Y}
            stroke="#222226"
            strokeWidth="1"
            strokeDasharray="2 4"
          />
        ))}
        {/* zero line */}
        {showZero && (
          <line
            x1={PAD_X}
            x2={W - PAD_X}
            y1={zeroY}
            y2={zeroY}
            stroke="#2A2A2E"
            strokeWidth="1"
          />
        )}
        {/* area fill */}
        <path d={areaPath} fill={stroke} fillOpacity="0.08" />
        {/* line */}
        <path
          d={linePath}
          fill="none"
          stroke={stroke}
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {/* end dot */}
        <circle cx={xs(data.length - 1)} cy={ys(last)} r="3" fill={stroke} />
      </svg>
    );
  }, [data, height, color, showZero]);
}

// ----- Donut chart (Signal distribution) --------------------------
function DonutChart({ slices, size = 168, thickness = 18 }) {
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  const cx = size / 2;
  const cy = size / 2;
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  let acc = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke="#222226"
        strokeWidth={thickness}
      />
      {slices.map((s, i) => {
        const frac = s.value / total;
        const dash = frac * c;
        const gap = c - dash;
        const offset = -acc * c;
        acc += frac;
        return (
          <circle
            key={i}
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={s.color}
            strokeWidth={thickness}
            strokeDasharray={`${dash} ${gap}`}
            strokeDashoffset={offset}
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        );
      })}
    </svg>
  );
}

// ----- Sparkline (bars) -------------------------------------------
function SparkBars({ data, height = 32, color = "#3B82F6", gap = 1 }) {
  const max = Math.max(...data, 1);
  const W = 200;
  const barW = (W - gap * (data.length - 1)) / data.length;
  return (
    <svg
      viewBox={`0 0 ${W} ${height}`}
      preserveAspectRatio="none"
      style={{ width: "100%", height }}
    >
      {data.map((v, i) => {
        const h = Math.max(1, (v / max) * (height - 2));
        const x = i * (barW + gap);
        const y = height - h;
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barW}
            height={h}
            fill={color}
            fillOpacity={0.55 + 0.45 * (v / max)}
          />
        );
      })}
    </svg>
  );
}

// ----- Sparkline (line) -------------------------------------------
function SparkLine({
  data,
  height = 36,
  color = "#F5F5F5",
  strokeWidth = 1.25,
}) {
  if (!data || data.length === 0) return null;
  const W = 240;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const xs = (i) => (i / (data.length - 1)) * W;
  const ys = (v) => 2 + (1 - (v - min) / range) * (height - 4);
  const d = data
    .map(
      (v, i) =>
        `${i === 0 ? "M" : "L"} ${xs(i).toFixed(1)} ${ys(v).toFixed(1)}`,
    )
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${W} ${height}`}
      preserveAspectRatio="none"
      style={{ width: "100%", height }}
    >
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

window.KALSHI_CHARTS = { PnlChart, DonutChart, SparkBars, SparkLine };
