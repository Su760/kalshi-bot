PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS markets (
    ticker                TEXT PRIMARY KEY,
    event_ticker          TEXT NOT NULL,
    series_ticker         TEXT NOT NULL,
    category              TEXT NOT NULL,
    title                 TEXT,
    subtitle              TEXT,
    status                TEXT NOT NULL,
    strike_type           TEXT,
    floor_strike          TEXT,
    cap_strike            TEXT,
    tick_size             TEXT NOT NULL,
    price_level_structure TEXT NOT NULL,
    open_time_ms          INTEGER,
    close_time_ms         INTEGER NOT NULL,
    latest_expiration_ms  INTEGER,
    settlement_source     TEXT,
    volume_24h            INTEGER DEFAULT 0,
    open_interest         INTEGER DEFAULT 0,
    last_price_cents      INTEGER,
    first_seen_ms         INTEGER NOT NULL,
    last_refreshed_ms     INTEGER NOT NULL,
    raw_json              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_markets_category   ON markets(category);
CREATE INDEX IF NOT EXISTS idx_markets_event      ON markets(event_ticker);
CREATE INDEX IF NOT EXISTS idx_markets_status     ON markets(status);
CREATE INDEX IF NOT EXISTS idx_markets_close_time ON markets(close_time_ms);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker         TEXT NOT NULL,
    ts_ms          INTEGER NOT NULL,
    seq            INTEGER,
    yes_bids_json  TEXT NOT NULL,
    no_bids_json   TEXT NOT NULL,
    best_yes_bid   TEXT,
    best_no_bid    TEXT,
    yes_ask_impl   TEXT,
    no_ask_impl    TEXT,
    mid_yes        TEXT,
    spread_cents   INTEGER,
    source         TEXT NOT NULL,
    FOREIGN KEY (ticker) REFERENCES markets(ticker)
);
CREATE INDEX IF NOT EXISTS idx_ob_ticker_ts ON orderbook_snapshots(ticker, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_ob_ts        ON orderbook_snapshots(ts_ms);

CREATE TABLE IF NOT EXISTS trades (
    trade_id         TEXT PRIMARY KEY,
    ticker           TEXT NOT NULL,
    ts_ms            INTEGER NOT NULL,
    side             TEXT NOT NULL,
    action           TEXT NOT NULL,
    yes_price        TEXT NOT NULL,
    count            INTEGER NOT NULL,
    is_our_fill      INTEGER NOT NULL DEFAULT 0,
    our_order_id     TEXT,
    client_order_id  TEXT,
    is_taker         INTEGER,
    fee_cents        INTEGER,
    slippage_cents   INTEGER,
    FOREIGN KEY (ticker) REFERENCES markets(ticker)
);
CREATE INDEX IF NOT EXISTS idx_trades_ticker_ts ON trades(ticker, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_trades_our       ON trades(is_our_fill, ts_ms DESC);

CREATE TABLE IF NOT EXISTS orders (
    client_order_id   TEXT PRIMARY KEY,
    order_id          TEXT UNIQUE,
    ticker            TEXT NOT NULL,
    side              TEXT NOT NULL,
    action            TEXT NOT NULL,
    price_dollars     TEXT NOT NULL,
    count             INTEGER NOT NULL,
    time_in_force     TEXT NOT NULL,
    post_only         INTEGER NOT NULL DEFAULT 1,
    status            TEXT NOT NULL,
    reject_code       TEXT,
    filled_count      INTEGER NOT NULL DEFAULT 0,
    created_ts_ms     INTEGER NOT NULL,
    acked_ts_ms       INTEGER,
    terminal_ts_ms    INTEGER,
    signal_module     TEXT,
    my_probability    TEXT,
    expected_edge     TEXT,
    expected_fee      TEXT,
    kelly_fraction    TEXT,
    raw_request_json  TEXT,
    raw_response_json TEXT,
    FOREIGN KEY (ticker) REFERENCES markets(ticker)
);
CREATE INDEX IF NOT EXISTS idx_orders_ticker ON orders(ticker);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_module ON orders(signal_module);

CREATE TABLE IF NOT EXISTS model_predictions (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                 TEXT NOT NULL,
    module                 TEXT NOT NULL,
    ts_ms                  INTEGER NOT NULL,
    my_probability         TEXT NOT NULL,
    market_price_yes       TEXT,
    edge_raw               TEXT,
    edge_net_of_fee        TEXT,
    confidence             TEXT NOT NULL,
    data_freshness_seconds INTEGER NOT NULL,
    resolved_outcome       INTEGER,
    resolved_ts_ms         INTEGER,
    debug_json             TEXT,
    FOREIGN KEY (ticker) REFERENCES markets(ticker)
);
CREATE INDEX IF NOT EXISTS idx_pred_ticker_ts  ON model_predictions(ticker, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_pred_module     ON model_predictions(module, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_pred_unresolved ON model_predictions(resolved_outcome)
    WHERE resolved_outcome IS NULL;

CREATE TABLE IF NOT EXISTS calibration_residuals (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    module             TEXT NOT NULL,
    scope              TEXT NOT NULL,
    ts_ms              INTEGER NOT NULL,
    forecast_value     TEXT NOT NULL,
    actual_value       TEXT,
    residual           TEXT,
    forecast_horizon_h INTEGER,
    metadata_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_calib_scope_ts ON calibration_residuals(module, scope, ts_ms DESC);

CREATE TABLE IF NOT EXISTS pnl_log (
    date_utc          TEXT PRIMARY KEY,
    opening_balance   TEXT NOT NULL,
    closing_balance   TEXT NOT NULL,
    realized_pnl      TEXT NOT NULL,
    unrealized_pnl    TEXT NOT NULL,
    fees_paid         TEXT NOT NULL,
    trade_count       INTEGER NOT NULL,
    win_count         INTEGER NOT NULL,
    peak_balance      TEXT NOT NULL,
    trough_balance    TEXT NOT NULL,
    max_drawdown_pct  TEXT NOT NULL,
    kill_events       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS heartbeats (
    thread_name TEXT PRIMARY KEY,
    ts_ms       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    reason       TEXT NOT NULL,
    context_json TEXT NOT NULL
);
