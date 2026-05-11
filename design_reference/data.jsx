// Mock data generators for Kalshi bot dashboard.
// Designed to feel real: deterministic seed -> stable rows on reload,
// then a few rolling fields tick over time.

const SEED_TICKERS = [
  // Sports
  { t: "KXNBA-26-BOS", title: "NBA Champion 2026 — Boston Celtics" },
  { t: "KXNBA-26-OKC", title: "NBA Champion 2026 — Oklahoma City" },
  { t: "KXNBA-26-DEN", title: "NBA Champion 2026 — Denver Nuggets" },
  { t: "KXNBA-26-NYK", title: "NBA Champion 2026 — New York Knicks" },
  { t: "KXMLB-26-LAD", title: "MLB World Series 2026 — Dodgers" },
  { t: "KXMLB-26-NYY", title: "MLB World Series 2026 — Yankees" },
  { t: "KXNFL-SB26-KC", title: "Super Bowl LX — Kansas City" },
  { t: "KXNFL-SB26-DET", title: "Super Bowl LX — Detroit" },
  // Weather
  { t: "KXHIGHCHI-26MAY09-T72", title: "Chicago high May 9 ≥ 72°F" },
  { t: "KXHIGHNY-26MAY09-T68", title: "NYC high May 9 ≥ 68°F" },
  { t: "KXHIGHLAX-26MAY09-T78", title: "LAX high May 9 ≥ 78°F" },
  // Politics / policy
  {
    t: "KXMOVVAREDISTRICT-26APR21-YES-P4",
    title: "VA redistricting passes Apr 21",
  },
  { t: "KXFEDDECISION-26JUN-25BP", title: "Fed cuts 25bp at June meeting" },
  { t: "KXFEDDECISION-26JUN-50BP", title: "Fed cuts 50bp at June meeting" },
  { t: "KXFEDDECISION-26JUN-HOLD", title: "Fed holds rates at June meeting" },
  { t: "KXSCOTUS-26-IMMIG", title: "SCOTUS rules on Trump v. CASA" },
  // Crypto / macro
  { t: "KXBTC-26MAY09-90K", title: "BTC closes ≥ $90k May 9" },
  { t: "KXBTC-26MAY09-95K", title: "BTC closes ≥ $95k May 9" },
  { t: "KXETH-26MAY-3K", title: "ETH closes ≥ $3k end-May" },
  { t: "KXCPI-26MAY-CORE3", title: "Core CPI ≥ 3.0% May print" },
  // Awards / culture
  { t: "KXOSCAR-26-BESTPIC-ANORA", title: "Best Picture 2026 — Anora" },
  { t: "KXTIME-26-POY", title: "Time Person of the Year 2026" },
];

const DETECTORS = [
  "bracket_sum_arb",
  "thin_spread",
  "bracket_sum_arb",
  "thin_spread",
  "bracket_sum_arb",
];

// Seeded RNG so reloads give a stable-feeling dataset.
function mulberry32(seed) {
  return function () {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(0xc1a0);
const pick = (arr) => arr[Math.floor(rand() * arr.length)];

function randomBetween(min, max, decimals = 2) {
  const v = min + rand() * (max - min);
  return Math.round(v * 10 ** decimals) / 10 ** decimals;
}

// ---- Recent signals (last ~20) ----------------------------------
function buildSignals(now) {
  const rows = [];
  let ts = now - 1000; // most recent ~1s ago
  for (let i = 0; i < 24; i++) {
    const detector = pick(DETECTORS);
    const market = pick(SEED_TICKERS);
    const edgeRaw =
      detector === "bracket_sum_arb"
        ? randomBetween(0.018, 0.082, 4)
        : randomBetween(0.012, 0.061, 4);
    // Most signals get fired; some skipped/blocked
    const r = rand();
    let action = "FIRED";
    let reason = "";
    if (edgeRaw < 0.022) {
      action = "SKIPPED";
      reason = "edge<min_net";
    } else if (r < 0.18) {
      action = "SKIPPED";
      reason = "dedup_5m";
    } else if (r < 0.24) {
      action = "BLOCKED";
      reason = "risk:position_cap";
    } else if (r < 0.28) {
      action = "BLOCKED";
      reason = "risk:daily_loss";
    }
    rows.push({
      ts,
      ticker: market.t,
      detector,
      edge: edgeRaw,
      side: rand() < 0.55 ? "YES" : "NO",
      price: randomBetween(0.18, 0.82, 2),
      action,
      reason,
    });
    // Step back a random 8s..3min
    ts -= Math.round((8 + rand() * 170) * 1000);
  }
  return rows;
}

// ---- Active positions -------------------------------------------
function buildPositions() {
  const picks = [];
  const used = new Set();
  while (picks.length < 7) {
    const m = pick(SEED_TICKERS);
    if (used.has(m.t)) continue;
    used.add(m.t);
    const side = rand() < 0.6 ? "YES" : "NO";
    const entry = randomBetween(0.18, 0.78, 2);
    const drift = (rand() - 0.45) * 0.16;
    const current = Math.max(0.02, Math.min(0.98, +(entry + drift).toFixed(2)));
    const size = Math.round(50 + rand() * 480);
    const heldMs = Math.round((4 + rand() * 38) * 3600 * 1000);
    picks.push({
      ticker: m.t,
      side,
      size,
      entry,
      current,
      heldMs,
    });
  }
  return picks;
}

// ---- 7-day P&L curve --------------------------------------------
function buildPnlSeries() {
  const points = [];
  let v = 0;
  // 7 days * 24 hourly points = 168 points
  for (let i = 0; i < 168; i++) {
    const drift = 0.42; // mean-positive
    v += (rand() - 0.5 + drift * 0.04) * 14;
    points.push(+v.toFixed(2));
  }
  // Force an obvious +ve trend
  return points.map((p, i) => +(p + i * 0.85).toFixed(2));
}

// ---- 24h signals fired sparkline (hourly) -----------------------
function buildSignals24h() {
  const arr = [];
  for (let i = 0; i < 24; i++) arr.push(Math.round(2 + rand() * 9));
  return arr;
}

// ---- Scans-per-minute over last hour (60 points) ----------------
function buildScansPerMin() {
  const arr = [];
  for (let i = 0; i < 60; i++) {
    arr.push(Math.round(220 + (rand() - 0.5) * 80));
  }
  return arr;
}

window.KALSHI_DATA = {
  buildSignals,
  buildPositions,
  buildPnlSeries,
  buildSignals24h,
  buildScansPerMin,
  SEED_TICKERS,
};
