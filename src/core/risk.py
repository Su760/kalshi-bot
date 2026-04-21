"""Six-tier kill switch stack for the Kalshi trading bot.

Tier order (checked in sequence, cheapest first):
  1. Global kill flag (file + in-memory)
  2. Daily loss cap
  3. Per-market contract cap
  4. Per-event correlated exposure cap
  5. Trailing drawdown cap
  6. Dead-man heartbeat timeout

Rules:
  - KillSwitchActive must NEVER be caught anywhere except the top-level
    orchestrator main loop, which logs and exits.
  - Tiers 1, 2, 5, 6 trip the full kill switch (cancel all + set flag).
  - Tiers 3 and 4 raise RiskError (block this order only, no full kill).
  - trip() is idempotent — safe to call multiple times.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

import structlog

from src.config.settings import Settings
from src.core.client import KalshiClient
from src.core.execution import OrderIntent
from src.core.risk_stub import KillSwitchActive, RiskError
from src.observability.metrics import kill_switch_trips_total, risk_checks_total

logger = structlog.get_logger(__name__)


class RiskManager:
    """Six-tier kill switch stack.

    The executor must call `check(intent)` before every order placement.
    KillSwitchActive propagates to the main loop; RiskError blocks one order.
    """

    def __init__(
        self,
        client: KalshiClient,
        settings: Settings,
        db_conn: sqlite3.Connection | None = None,
        executor: Any | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._db = db_conn
        self._executor = executor
        self._killed = False
        self._balance_cents: int = 0
        self._peak_balance_cents: int = 0
        self._start_of_day_balance_cents: int = 0
        self._last_balance_refresh_ms: int = 0
        self._lock = threading.Lock()
        self._refresh_balance()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_executor(self, executor: Any) -> None:
        """Inject executor after construction (avoids circular dependency)."""
        self._executor = executor

    def check(self, intent: OrderIntent) -> None:
        """Run all six tiers in order. Raises on any violation.

        KillSwitchActive propagates — never catch it here.
        """
        risk_checks_total.inc()
        with self._lock:
            self._maybe_refresh_balance()
            self._check_tier1_kill_flag()
            self._check_tier2_daily_loss()
            self._check_tier3_per_market(intent)
            self._check_tier4_per_event(intent)
            self._check_tier5_drawdown()
            self._check_tier6_heartbeat()

    def trip(self, reason: str, context: dict[str, Any]) -> None:
        """Trip the full kill switch. Idempotent."""
        if self._killed:
            return
        self._killed = True
        kill_switch_trips_total.labels(reason=reason).inc()
        logger.error("risk_kill_switch_tripped", reason=reason, context=context)
        if self._db is not None:
            try:
                self._db.execute(
                    "INSERT INTO kill_events (ts_ms, reason, context_json) VALUES (?, ?, ?)",
                    (int(time.time() * 1000), reason, json.dumps(context)),
                )
                self._db.commit()
            except Exception:
                logger.exception("kill_event_persist_failed")
        if self._executor is not None:
            try:
                self._executor.cancel_all()
            except Exception:
                logger.exception("cancel_all_on_trip_failed")
        try:
            kill_file = self._settings.KILL_SWITCH_FILE
            with open(kill_file, "w") as f:
                f.write(f"{reason}\n")
        except Exception:
            logger.exception("kill_file_write_failed")

    def on_utc_rollover(self) -> None:
        """Reset daily loss counter. Call at 00:00 UTC."""
        with self._lock:
            self._start_of_day_balance_cents = self._balance_cents

    # ------------------------------------------------------------------
    # Tier checks
    # ------------------------------------------------------------------

    def _check_tier1_kill_flag(self) -> None:
        """Tier 1: global kill. Cheapest check — always first."""
        if self._killed:
            raise KillSwitchActive("in-memory kill flag set")
        kill_file = self._settings.KILL_SWITCH_FILE
        if os.path.exists(kill_file):
            self._killed = True
            raise KillSwitchActive(f"kill file exists: {kill_file}")

    def _check_tier2_daily_loss(self) -> None:
        """Tier 2: daily loss cap."""
        loss_cents = self._start_of_day_balance_cents - self._balance_cents
        max_loss_cents = int(self._settings.MAX_DAILY_LOSS_USD * 100)
        if loss_cents > max_loss_cents:
            self.trip(
                "daily_loss",
                {
                    "loss_cents": loss_cents,
                    "max_loss_cents": max_loss_cents,
                    "start_balance": self._start_of_day_balance_cents,
                    "current_balance": self._balance_cents,
                },
            )
            raise KillSwitchActive("daily loss cap exceeded")

    def _check_tier3_per_market(self, intent: OrderIntent) -> None:
        """Tier 3: per-market contract cap. Raises RiskError, not KillSwitchActive."""
        if self._db is None:
            return
        current = self._get_open_contracts(intent.ticker)
        if current + intent.count > self._settings.MAX_PER_MARKET_CONTRACTS:
            raise RiskError(
                f"per-market cap: {current + intent.count} > "
                f"{self._settings.MAX_PER_MARKET_CONTRACTS} for {intent.ticker}"
            )

    def _check_tier4_per_event(self, intent: OrderIntent) -> None:
        """Tier 4: correlated exposure cap across all markets in same event."""
        if self._db is None:
            return
        if self._balance_cents == 0:
            return
        row = self._db.execute(
            "SELECT event_ticker FROM markets WHERE ticker = ?",
            (intent.ticker,),
        ).fetchone()
        if row is None:
            return
        event_ticker = row[0]
        event_exposure_cents = self._get_event_exposure_cents(event_ticker)
        new_exposure_cents = event_exposure_cents + (
            intent.count * int(float(str(intent.price_dollars)) * 100)
        )
        max_exposure_cents = int(self._balance_cents * self._settings.MAX_PER_EVENT_PCT)
        if new_exposure_cents > max_exposure_cents:
            raise RiskError(
                f"per-event cap: {new_exposure_cents} > {max_exposure_cents} "
                f"cents for event {event_ticker}"
            )

    def _check_tier5_drawdown(self) -> None:
        """Tier 5: peak-to-trough drawdown."""
        if self._peak_balance_cents == 0:
            return
        drawdown = (
            self._peak_balance_cents - self._balance_cents
        ) / self._peak_balance_cents
        if drawdown > self._settings.MAX_DRAWDOWN_PCT:
            self.trip(
                "drawdown",
                {
                    "peak_balance": self._peak_balance_cents,
                    "current_balance": self._balance_cents,
                    "drawdown_pct": round(drawdown, 4),
                    "max_drawdown_pct": self._settings.MAX_DRAWDOWN_PCT,
                },
            )
            raise KillSwitchActive("drawdown cap exceeded")

    def _check_tier6_heartbeat(self) -> None:
        """Tier 6: dead-man heartbeat. If no ping in HEARTBEAT_TIMEOUT_S, kill."""
        if self._db is None:
            return
        row = self._db.execute(
            "SELECT ts_ms FROM heartbeats WHERE thread_name = 'main'"
        ).fetchone()
        if row is None:
            return
        now_ms = int(time.time() * 1000)
        age_s = (now_ms - row[0]) / 1000
        if age_s > self._settings.HEARTBEAT_TIMEOUT_S:
            self.trip(
                "heartbeat",
                {
                    "last_heartbeat_age_s": round(age_s, 1),
                    "timeout_s": self._settings.HEARTBEAT_TIMEOUT_S,
                },
            )
            raise KillSwitchActive("heartbeat timeout")

    # ------------------------------------------------------------------
    # Balance + DB helpers
    # ------------------------------------------------------------------

    def _refresh_balance(self) -> None:
        """Fetch balance from Kalshi API and update cached values."""
        try:
            resp = self._client.get_balance()
            balance = int(resp.get("balance", 0))
            self._balance_cents = balance
            if balance > self._peak_balance_cents:
                self._peak_balance_cents = balance
            if self._start_of_day_balance_cents == 0:
                self._start_of_day_balance_cents = balance
            self._last_balance_refresh_ms = int(time.time() * 1000)
        except Exception:
            logger.warning("risk_balance_refresh_failed")

    def _maybe_refresh_balance(self) -> None:
        now_ms = int(time.time() * 1000)
        elapsed_s = (now_ms - self._last_balance_refresh_ms) / 1000
        if elapsed_s > self._settings.RISK_BALANCE_REFRESH_INTERVAL_S:
            self._refresh_balance()

    def _get_open_contracts(self, ticker: str) -> int:
        """Sum of contracts in open orders for this ticker."""
        if self._db is None:
            return 0
        row = self._db.execute(
            """SELECT COALESCE(SUM(count), 0) FROM orders
               WHERE ticker = ? AND status IN ('pending', 'resting', 'partial')""",
            (ticker,),
        ).fetchone()
        return int(row[0]) if row else 0

    def _get_event_exposure_cents(self, event_ticker: str) -> int:
        """Total notional exposure in cents for all open orders in this event."""
        if self._db is None:
            return 0
        rows = self._db.execute(
            """SELECT o.count, o.price_dollars FROM orders o
               JOIN markets m ON o.ticker = m.ticker
               WHERE m.event_ticker = ? AND o.status IN ('pending', 'resting', 'partial')""",
            (event_ticker,),
        ).fetchall()
        total = 0
        for count, price_str in rows:
            total += int(count) * int(float(price_str) * 100)
        return total
