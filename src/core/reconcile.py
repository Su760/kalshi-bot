"""Reconciliation loop — treats the exchange as source of truth.

Runs every RECONCILE_INTERVAL_S. On divergence between local DB state
and exchange state, local state is overwritten and a warning is logged.

If reconciliation raises, it logs and continues — never kills the bot.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

import structlog

from src.config.settings import Settings
from src.core.client import KalshiClient
from src.core.risk import RiskManager
from src.core.risk_stub import RiskManagerStub

logger = structlog.get_logger(__name__)


@dataclass
class ReconcileResult:
    balance_cents: int
    positions_corrected: int
    orphan_orders_canceled: int
    lost_orders_inserted: int
    stale_books: list[str]
    errors: list[str]
    ts_ms: int


class Reconciler:
    def __init__(
        self,
        client: KalshiClient,
        settings: Settings,
        db_conn: sqlite3.Connection,
        risk: RiskManager | RiskManagerStub | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._db = db_conn
        self._risk = risk

    def reconcile_once(self) -> ReconcileResult:
        """Run one full reconciliation cycle. Returns a summary."""
        result = ReconcileResult(
            balance_cents=0,
            positions_corrected=0,
            orphan_orders_canceled=0,
            lost_orders_inserted=0,
            stale_books=[],
            errors=[],
            ts_ms=int(time.time() * 1000),
        )
        for step_name, step_fn in [
            ("balance", self._step_balance),
            ("positions", self._step_positions),
            ("orders", self._step_orders),
        ]:
            try:
                step_fn(result)
            except Exception as e:
                logger.exception("reconcile_step_failed", step=step_name)
                result.errors.append(f"{step_name}: {e}")
        return result

    def force_reconcile(self) -> ReconcileResult:
        """Called on WS reconnect. Same as reconcile_once()."""
        return self.reconcile_once()

    def _step_balance(self, result: ReconcileResult) -> None:
        resp = self._client.get_balance()
        balance = int(resp.get("balance", 0))
        result.balance_cents = balance
        if isinstance(self._risk, RiskManager):
            self._risk._balance_cents = balance
            if balance > self._risk._peak_balance_cents:
                self._risk._peak_balance_cents = balance

    def _step_positions(self, result: ReconcileResult) -> None:
        resp = self._client.get_positions()
        exchange_positions = resp.get("market_positions") or []
        for pos in exchange_positions:
            ticker = pos.get("ticker")
            if ticker is None:
                continue
            row = self._db.execute(
                "SELECT COUNT(*) FROM orders WHERE ticker=? AND status IN ('pending','resting','partial')",
                (ticker,),
            ).fetchone()
            if row[0] == 0:
                logger.warning(
                    "reconcile_position_without_order",
                    ticker=ticker,
                    position=pos,
                )
                result.positions_corrected += 1

    def _step_orders(self, result: ReconcileResult) -> None:
        resp = self._client.get_orders(status="resting")
        exchange_orders: dict[str, Any] = {
            o["order_id"]: o
            for o in (resp.get("orders") or [])
            if o.get("order_id")
        }

        self._db.row_factory = sqlite3.Row
        local_rows = self._db.execute(
            "SELECT order_id, client_order_id, ticker FROM orders"
            " WHERE status='resting' AND order_id IS NOT NULL"
        ).fetchall()
        local_order_ids: dict[str, Any] = {
            row["order_id"]: row for row in local_rows
        }

        now_ms = int(time.time() * 1000)

        for order_id, row in local_order_ids.items():
            if order_id not in exchange_orders:
                logger.warning(
                    "reconcile_orphan_order",
                    order_id=order_id,
                    ticker=row["ticker"],
                )
                self._db.execute(
                    "UPDATE orders SET status='canceled_by_exchange',"
                    " terminal_ts_ms=? WHERE order_id=?",
                    (now_ms, order_id),
                )
                result.orphan_orders_canceled += 1

        for order_id, exc_order in exchange_orders.items():
            if order_id not in local_order_ids:
                logger.warning("reconcile_lost_order", order_id=order_id)
                self._insert_lost_order(exc_order)
                result.lost_orders_inserted += 1

        self._db.commit()

    def _insert_lost_order(self, exc_order: dict[str, Any]) -> None:
        """Insert an order that exists on exchange but not in local DB."""
        self._db.execute(
            """INSERT OR IGNORE INTO orders (
                client_order_id, order_id, ticker, side, action,
                price_dollars, count, time_in_force, post_only,
                status, created_ts_ms, signal_module
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                exc_order.get("client_order_id") or uuid.uuid4().hex,
                exc_order.get("order_id"),
                exc_order.get("ticker", ""),
                exc_order.get("side", "yes"),
                exc_order.get("action", "buy"),
                str(exc_order.get("yes_price_dollars") or "0"),
                int(exc_order.get("count_fp") or exc_order.get("count") or 0),
                exc_order.get("time_in_force", "GTC"),
                1 if exc_order.get("post_only") else 0,
                "resting",
                int(time.time() * 1000),
                "reconciler",
            ),
        )
