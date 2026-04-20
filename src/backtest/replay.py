"""Backtest replay engine — drives signal modules over historical orderbook snapshots."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.backtest.metrics import (
    brier_score,
    brier_skill_score,
    calibration_buckets,
    max_drawdown,
    pnl_z_score,
    sharpe_ratio,
)
from src.backtest.portfolio import VirtualPortfolio
from src.core.types import Market, Orderbook, PriceLevel
from src.modules.base import SignalModule


@dataclass
class BacktestConfig:
    module_name: str
    from_ts_ms: int
    to_ts_ms: int
    min_edge_pct: float = 0.08
    min_net_edge_pct: float = 0.02
    kelly_fraction: float = 0.25
    starting_bankroll: float = 1000.0
    max_contracts: int = 100


@dataclass
class BacktestResult:
    config: BacktestConfig
    total_bets: int
    resolved_bets: int
    realized_pnl: float
    brier_score: float
    brier_skill_score: float
    pnl_z_score: float
    sharpe_ratio: float
    max_drawdown: float
    calibration: list[dict]  # type: ignore[type-arg]
    gate_pass: bool
    equity_curve: list[float]
    predictions: list[dict]  # type: ignore[type-arg]


def _row_to_market(market_row: sqlite3.Row) -> Market:
    return Market(
        ticker=market_row["ticker"],
        event_ticker=market_row["event_ticker"],
        series_ticker=market_row["series_ticker"],
        category=market_row["category"],
        title=market_row["title"],
        subtitle=market_row["subtitle"],
        status=market_row["status"],
        strike_type=market_row["strike_type"],
        floor_strike=market_row["floor_strike"],
        cap_strike=market_row["cap_strike"],
        tick_size=market_row["tick_size"],
        price_level_structure=market_row["price_level_structure"],
        open_time_ms=market_row["open_time_ms"],
        close_time_ms=market_row["close_time_ms"] or 0,
        latest_expiration_ms=market_row["latest_expiration_ms"],
        settlement_source=market_row["settlement_source"],
        volume_24h=market_row["volume_24h"] or 0,
        open_interest=market_row["open_interest"] or 0,
        last_price_cents=market_row["last_price_cents"],
        raw_json=market_row["raw_json"],
    )


def _row_to_orderbook(row: sqlite3.Row) -> Orderbook:
    yes_bids_raw: list[list[Any]] = json.loads(row["yes_bids_json"] or "[]")
    no_bids_raw: list[list[Any]] = json.loads(row["no_bids_json"] or "[]")
    yes_bids = [PriceLevel(price=Decimal(str(p)), size=int(s)) for p, s in yes_bids_raw]
    no_bids = [PriceLevel(price=Decimal(str(p)), size=int(s)) for p, s in no_bids_raw]
    return Orderbook(
        ticker=row["ticker"],
        seq=row["seq"] or 0,
        yes_bids=yes_bids,
        no_bids=no_bids,
        ts_ms=row["ts_ms"],
    )


class Replay:
    def __init__(
        self,
        db_conn: sqlite3.Connection,
        module: SignalModule,
        config: BacktestConfig,
    ) -> None:
        self._db = db_conn
        self._module = module
        self._config = config

    def run(self) -> BacktestResult:
        portfolio = VirtualPortfolio(
            starting_bankroll=self._config.starting_bankroll,
            kelly_fraction=self._config.kelly_fraction,
            max_contracts=self._config.max_contracts,
        )

        predictions: list[dict[str, Any]] = []

        snapshots = self._db.execute(
            "SELECT * FROM orderbook_snapshots "
            "WHERE ts_ms BETWEEN ? AND ? ORDER BY ts_ms ASC",
            (self._config.from_ts_ms, self._config.to_ts_ms),
        ).fetchall()

        for snap in snapshots:
            ticker: str = snap["ticker"]
            market_row = self._db.execute(
                "SELECT * FROM markets WHERE ticker = ?", (ticker,)
            ).fetchone()
            if market_row is None:
                continue

            market = _row_to_market(market_row)
            ob = _row_to_orderbook(snap)
            now = datetime.fromtimestamp(snap["ts_ms"] / 1000, tz=timezone.utc)

            if not self._module.applies_to(market):
                continue

            signal = self._module.predict(market, now)
            if signal is None:
                continue

            predictions.append(
                {
                    "ticker": ticker,
                    "ts_ms": snap["ts_ms"],
                    "my_probability": signal.my_probability,
                    "confidence": signal.confidence,
                }
            )

            if ob.yes_bids:
                fill_price = float(ob.yes_bids[0].price)
                contracts = portfolio.size_bet(
                    my_prob=signal.my_probability,
                    market_price=fill_price,
                )
                if contracts > 0:
                    portfolio.open_bet(
                        ticker=ticker,
                        side="yes",
                        contracts=contracts,
                        fill_price=fill_price,
                        my_probability=signal.my_probability,
                        ts_ms=snap["ts_ms"],
                    )

            # Settle any open bets whose markets have settled
            open_tickers = [b.ticker for b in portfolio.open_bets]
            if open_tickers:
                placeholders = ",".join("?" * len(open_tickers))
                settled_rows = self._db.execute(
                    f"SELECT ticker, last_price_cents FROM markets "
                    f"WHERE ticker IN ({placeholders}) AND status = 'settled'",
                    open_tickers,
                ).fetchall()
                for srow in settled_rows:
                    last_price: int = srow["last_price_cents"] or 50
                    outcome = 1 if last_price > 50 else 0
                    portfolio.settle_bet(srow["ticker"], outcome)

        # Final settlement pass for any remaining open bets
        for bet in list(portfolio.open_bets):
            market_row = self._db.execute(
                "SELECT * FROM markets WHERE ticker = ? AND status = 'settled'",
                (bet.ticker,),
            ).fetchone()
            if market_row is not None:
                last_price = market_row["last_price_cents"] or 50
                outcome = 1 if last_price > 50 else 0
                portfolio.settle_bet(bet.ticker, outcome)

        closed = portfolio.closed_bets
        realized_pnl = sum(b.pnl for b in closed)

        resolved_probs = [b.my_probability for b in closed]
        resolved_outcomes = [b.outcome for b in closed if b.outcome is not None]
        resolved_probs = resolved_probs[: len(resolved_outcomes)]

        bs = brier_score(resolved_probs, resolved_outcomes) if resolved_probs else 0.0
        bss = brier_skill_score(resolved_probs, resolved_outcomes) if resolved_probs else 0.0

        bet_tuples = [
            (float(b.contracts), b.cost_per_contract, b.my_probability) for b in closed
        ]
        z = pnl_z_score(realized_pnl, bet_tuples) if bet_tuples else 0.0

        equity = portfolio.equity_curve
        daily_pnl = [equity[i] - equity[i - 1] for i in range(1, len(equity))]
        sr = sharpe_ratio(daily_pnl) if len(daily_pnl) >= 2 else 0.0
        md = max_drawdown(equity) if equity else 0.0

        calib = calibration_buckets(resolved_probs, resolved_outcomes) if resolved_probs else []

        resolved_bets = len(closed)
        gate_pass = bss > 0 and resolved_bets >= 50 and z > 1.5

        return BacktestResult(
            config=self._config,
            total_bets=len(portfolio.open_bets) + resolved_bets,
            resolved_bets=resolved_bets,
            realized_pnl=realized_pnl,
            brier_score=bs,
            brier_skill_score=bss,
            pnl_z_score=z,
            sharpe_ratio=sr,
            max_drawdown=md,
            calibration=calib,
            gate_pass=gate_pass,
            equity_curve=equity,
            predictions=predictions,
        )
