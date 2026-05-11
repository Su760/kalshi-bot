// Main dashboard app — wires state, ticking timers, and tweaks.
const {
  useState: _useS,
  useEffect: _useE,
  useMemo: _useM,
  useRef: _useR,
} = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/ {
  density: "regular",
  accent: "green",
  showSparklines: true,
  tickerStyle: "full",
  panelGrid: "2-column",
}; /*EDITMODE-END*/

function App() {
  const t = (window.useTweaks || (() => [{}, () => {}]))(TWEAK_DEFAULTS);
  const tweaks = t[0];
  const setTweak = t[1];

  // ---- bootstrap data (stable per session) ----
  const dataRef = _useR(null);
  if (!dataRef.current) {
    const D = window.KALSHI_DATA;
    const now = Date.now();
    dataRef.current = {
      signals: D.buildSignals(now),
      positions: D.buildPositions(),
      pnl: D.buildPnlSeries(),
      sig24: D.buildSignals24h(),
      scans: D.buildScansPerMin(),
      bootMs: now - 1000 * 60 * 60 * 62 - 32 * 60 * 1000, // 2d 14h 32m ago
    };
  }
  const D = dataRef.current;

  // ---- live ticking state ----
  const [now, setNow] = _useS(Date.now());
  const [lastScan, setLastScan] = _useS(Date.now() - 2000);
  const [signals, setSignals] = _useS(D.signals);
  const [positions, setPositions] = _useS(D.positions);
  const [scans, setScans] = _useS(D.scans);
  const [pnl, setPnl] = _useS(D.pnl);
  const [mode, setMode] = _useS("PAPER");

  // tick clock
  _useE(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // tick scan rate every ~3s; occasionally append a new signal
  _useE(() => {
    const id = setInterval(() => {
      // refresh last scan
      const dt = 1500 + Math.random() * 3000;
      setLastScan(Date.now() - dt + Math.random() * 1500);
      // shift scans-per-minute window
      setScans((prev) => {
        const next = prev.slice(1);
        next.push(Math.round(220 + (Math.random() - 0.5) * 80));
        return next;
      });
      // 35% chance to drop a new signal
      if (Math.random() < 0.35) {
        setSignals((prev) => {
          const market =
            window.KALSHI_DATA.SEED_TICKERS[
              Math.floor(Math.random() * window.KALSHI_DATA.SEED_TICKERS.length)
            ];
          const detector =
            Math.random() < 0.6 ? "bracket_sum_arb" : "thin_spread";
          const edge =
            detector === "bracket_sum_arb"
              ? 0.018 + Math.random() * 0.07
              : 0.012 + Math.random() * 0.055;
          const r = Math.random();
          let action = "FIRED",
            reason = "";
          if (edge < 0.022) {
            action = "SKIPPED";
            reason = "edge<min_net";
          } else if (r < 0.18) {
            action = "SKIPPED";
            reason = "dedup_5m";
          } else if (r < 0.24) {
            action = "BLOCKED";
            reason = "risk:position_cap";
          }
          const row = {
            ts: Date.now(),
            ticker: market.t,
            detector,
            edge: +edge.toFixed(4),
            side: Math.random() < 0.55 ? "YES" : "NO",
            price: +(0.18 + Math.random() * 0.6).toFixed(2),
            action,
            reason,
          };
          return [row, ...prev].slice(0, 60);
        });
      }
      // jitter positions current prices a touch
      setPositions((prev) =>
        prev.map((p) => {
          const nextC = Math.max(
            0.02,
            Math.min(
              0.98,
              +(p.current + (Math.random() - 0.5) * 0.012).toFixed(2),
            ),
          );
          return { ...p, current: nextC, heldMs: p.heldMs + 3000 };
        }),
      );
      // gently nudge last p&l point
      setPnl((prev) => {
        const next = prev.slice();
        next[next.length - 1] = +(
          next[next.length - 1] +
          (Math.random() - 0.4) * 4
        ).toFixed(2);
        return next;
      });
    }, 3000);
    return () => clearInterval(id);
  }, []);

  const uptimeMs = now - D.bootMs;
  const lastScanAgo = window.fmtAgo(now - lastScan);

  // KPI computations
  const todayCount = signals.filter((s) => s.action === "FIRED").length;
  const sig24 = D.sig24;
  const exposure = positions.reduce((acc, p) => acc + p.entry * p.size, 0);
  const winRate = 62.0;
  const winSample = 47;
  const pnlValue = pnl[pnl.length - 1];
  const pnlPct =
    ((pnl[pnl.length - 1] - pnl[0]) / Math.max(1, Math.abs(pnl[0] || 1))) * 100;

  const dist = _useM(() => {
    const out = { bracket: 0, thin: 0, other: 0 };
    for (const s of signals.slice(0, 50)) {
      if (s.detector === "bracket_sum_arb") out.bracket++;
      else if (s.detector === "thin_spread") out.thin++;
      else out.other++;
    }
    out.other = Math.max(out.other, 6); // pretend a 3rd detector exists with low volume
    return out;
  }, [signals]);

  const onModeRequest = (m) => {
    if (m === "LIVE") {
      // locked — flash a confirm-style toast effect via class
      const el = document.querySelector(".mode-toggle");
      if (el) {
        el.classList.add("locked-flash");
        setTimeout(() => el.classList.remove("locked-flash"), 600);
      }
      return;
    }
    setMode(m);
  };

  const cur = scans[scans.length - 1];

  return (
    <div
      className={`app density-${tweaks.density} accent-${tweaks.accent} ticker-${tweaks.tickerStyle} grid-${tweaks.panelGrid}`}
    >
      <window.TopBar
        status={mode === "LIVE" ? "LIVE" : "PAPER"}
        uptimeMs={uptimeMs}
        lastScanAgo={lastScanAgo}
        mode={mode}
        onModeRequest={onModeRequest}
      />

      <main className="dashboard">
        <window.KpiStrip
          pnl={pnlValue}
          pnlPct={pnlPct}
          signalsToday={todayCount}
          signals24h={sig24}
          openPositions={positions.length}
          exposure={exposure}
          winRate={winRate}
          winSample={winSample}
        />

        <section className="grid-2col">
          <div className="col-left">
            <window.SignalsTable signals={signals} />
            <window.PositionsTable positions={positions} />
          </div>
          <div className="col-right">
            <window.PnlPanel series={pnl} />
            <window.DistributionPanel counts={dist} />
            <window.ScansPanel data={scans} />
          </div>
        </section>
      </main>

      <window.Footer
        build="0.7.3-rc2"
        sha="a3f29c1"
        dbBytes={284_910_336}
        logBytes={42_119_488}
        scanRate={cur / 60}
      />

      {window.TweaksPanel && (
        <window.TweaksPanel title="Tweaks">
          <window.TweakSection label="Density">
            <window.TweakRadio
              label="Rows"
              value={tweaks.density}
              onChange={(v) => setTweak("density", v)}
              options={[
                { value: "compact", label: "Compact" },
                { value: "regular", label: "Regular" },
              ]}
            />
          </window.TweakSection>
          <window.TweakSection label="Style">
            <window.TweakRadio
              label="P&L accent"
              value={tweaks.accent}
              onChange={(v) => setTweak("accent", v)}
              options={[
                { value: "green", label: "Green" },
                { value: "blue", label: "Blue" },
                { value: "amber", label: "Amber" },
                { value: "violet", label: "Violet" },
              ]}
            />
            <window.TweakRadio
              label="Ticker"
              value={tweaks.tickerStyle}
              onChange={(v) => setTweak("tickerStyle", v)}
              options={[
                { value: "full", label: "Full" },
                { value: "short", label: "Truncated" },
              ]}
            />
            <window.TweakToggle
              label="Sparklines"
              value={tweaks.showSparklines}
              onChange={(v) => setTweak("showSparklines", v)}
            />
          </window.TweakSection>
          <window.TweakSection label="Layout">
            <window.TweakRadio
              label="Panel grid"
              value={tweaks.panelGrid}
              onChange={(v) => setTweak("panelGrid", v)}
              options={[
                { value: "2-column", label: "2-col" },
                { value: "stacked", label: "Stacked" },
              ]}
            />
          </window.TweakSection>
        </window.TweaksPanel>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
