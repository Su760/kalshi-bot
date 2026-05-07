"""ScanLoop — per-tick scan over live orderbooks.

Called by OrchestratorLoop every SCAN_INTERVAL_S. For each market with a live
orderbook, calls scanner.predict() and submits orders on signal.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.config.settings import Settings
from src.core.execution import Executor, OrderIntent
from src.core.risk_stub import KillSwitchActive, RiskError
from src.core.scanner import Scanner
from src.core.sizing import kelly_contracts
from src.core.types import Market
from src.observability.metrics import signals_fired_total

logger = structlog.get_logger(__name__)


class ScanLoop:
    def __init__(
        self,
        scanner: Scanner,
        executor: Executor,
        db_conn: sqlite3.Connection,
        settings: Settings,
    ) -> None:
        self._scanner = scanner
        self._executor = executor
        self._db = db_conn
        self._settings = settings

    def run_once(self) -> int:
        """Scan all markets with live orderbooks. Returns number of signals fired."""
        now = datetime.now(tz=UTC)
        markets = self._load_open_markets()
        t0 = time.monotonic()
        logger.info(
            "scan_cycle_start",
            books_in_memory=len(self._scanner._books),
            markets_with_books=len(markets),
        )
        signals_fired = 0

        for market in markets:
            try:
                if not self._scanner.applies_to(market):
                    logger.debug(
                        "scanner_skip",
                        ticker=market.ticker,
                        reason="applies_to_false",
                        status=market.status,
                        volume_24h=market.volume_24h,
                        open_interest=market.open_interest,
                    )
                    continue
                signal = self._scanner.predict(market, now)
                if signal is None:
                    continue

                signals_fired += 1
                detector = str(signal.debug.get("detector", "unknown"))
                signals_fired_total.labels(module="scanner", detector=detector).inc()

                logger.info(
                    "signal_fired",
                    ticker=market.ticker,
                    prob=signal.my_probability,
                    confidence=signal.confidence,
                    detector=detector,
                    net_edge=signal.debug.get("net_edge"),
                )

                self._maybe_submit(market, signal)

            except KillSwitchActive:
                raise
            except Exception:
                logger.exception("scan_loop_market_error", ticker=market.ticker)

        elapsed_ms = round((time.monotonic() - t0) * 1000)
        logger.info(
            "scan_cycle_end",
            signals_generated=signals_fired,
            duration_ms=elapsed_ms,
        )
        return signals_fired

    def _maybe_submit(self, market: Market, signal: Any) -> None:
        """Submit an order if edge clears the minimum threshold."""
        book = self._scanner._books.get(market.ticker)
        if book is None:
            return

        ob = book.to_orderbook()
        if not ob.yes_bids:
            return

        fill_price = ob.yes_bids[0].price
        # TODO: replace hardcoded bankroll with RiskManager._balance_cents once wired.
        bankroll = Decimal("1000")

        contracts = kelly_contracts(
            my_prob=signal.my_probability,
            market_price=fill_price,
            bankroll_dollars=bankroll,
            kelly_fraction=self._settings.KELLY_FRACTION,
            max_contracts=self._settings.MAX_PER_MARKET_CONTRACTS,
            is_maker=True,
        )

        if contracts <= 0:
            return

        intent = OrderIntent(
            ticker=market.ticker,
            side="yes",
            action="buy",
            price_dollars=fill_price,
            count=contracts,
            signal_module="scanner",
            my_probability=signal.my_probability,
            kelly_fraction=self._settings.KELLY_FRACTION,
        )

        try:
            outcome = self._executor.submit(intent)
            logger.info(
                "order_submitted",
                ticker=market.ticker,
                status=outcome.status,
                contracts=contracts,
                price=float(fill_price),
            )
        except KillSwitchActive:
            raise
        except RiskError as exc:
            logger.warning("order_blocked_by_risk", ticker=market.ticker, reason=str(exc))
        except Exception:
            logger.exception("order_submit_failed", ticker=market.ticker)

    def _load_open_markets(self) -> list[Market]:
        """Load open markets that have live orderbooks."""
        rows = self._db.execute(
            "SELECT * FROM markets WHERE status IN ('active', 'open')"
        ).fetchall()
        markets: list[Market] = []
        for row in rows:
            ticker = row["ticker"]
            if ticker not in self._scanner._books:
                continue
            try:
                markets.append(
                    Market(
                        ticker=ticker,
                        event_ticker=row["event_ticker"],
                        series_ticker=row["series_ticker"],
                        category=row["category"],
                        title=row["title"],
                        subtitle=row["subtitle"],
                        status=row["status"],
                        strike_type=row["strike_type"],
                        floor_strike=row["floor_strike"],
                        cap_strike=row["cap_strike"],
                        tick_size=row["tick_size"],
                        price_level_structure=row["price_level_structure"],
                        open_time_ms=row["open_time_ms"],
                        close_time_ms=row["close_time_ms"] or 0,
                        latest_expiration_ms=row["latest_expiration_ms"],
                        settlement_source=row["settlement_source"],
                        volume_24h=row["volume_24h"] or 0,
                        open_interest=row["open_interest"] or 0,
                        last_price_cents=row["last_price_cents"],
                        raw_json=row["raw_json"],
                    )
                )
            except Exception:
                logger.exception("scan_loop_market_parse_failed", ticker=ticker)
                continue
        return markets
