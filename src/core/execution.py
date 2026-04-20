"""Phase 4 execution engine — REST-only, limit, idempotent order placement.

Locked decisions (see phase plan):
  * Orders are REST. Limit orders only. Default post_only=True, TIF=GTC.
  * Every order gets client_order_id = uuid4().hex BEFORE any API call.
  * On timeout or ORDER_ALREADY_EXISTS: GET /portfolio/orders?client_order_id=<id>
    to decide whether to retry or return the existing order. Never resubmit blind.
  * Terminal reject codes are returned as rejected outcomes, not retried.
  * Paper mode is the default (LIVE_TRADING=False).
  * KillSwitchActive must never be caught here — it propagates to the caller.
  * Order bodies use count_fp and yes_price_dollars — NEVER count or yes_price.
"""
from __future__ import annotations

import json
import random
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import structlog

from src.config.settings import Settings
from src.core.client import KalshiClient, KalshiHTTPError
from src.core.risk_stub import RiskManagerStub

if TYPE_CHECKING:
    from src.core.risk import RiskManager

logger = structlog.get_logger(__name__)


_TERMINAL_REJECT_CODES: frozenset[str] = frozenset({
    "INSUFFICIENT_BALANCE",
    "MARKET_NOT_FOUND",
    "INVALID_PRICE",
    "EXCHANGE_PAUSED",
    "TRADING_PAUSED",
    "SELF_CROSS_ATTEMPT",
    "EXCEEDED_PER_MARKET_RISK_LIMIT",
    "EXCEEDED_ORDER_GROUP_RISK_LIMIT",
    "POST_ONLY_CROSS",
})


@dataclass
class OrderIntent:
    ticker: str
    side: str                     # 'yes' | 'no'
    action: str                   # 'buy' | 'sell'
    price_dollars: Decimal        # limit price in dollars [0, 1]
    count: int                    # contracts (maps to count_fp on the wire)
    time_in_force: str = "GTC"
    post_only: bool = True
    signal_module: str = "scanner"
    my_probability: float | None = None
    kelly_fraction: float | None = None


@dataclass
class OrderOutcome:
    client_order_id: str
    order_id: str | None = None
    status: str = "pending"       # 'paper' | 'resting' | 'filled' | 'rejected' | 'error'
    reject_code: str | None = None
    filled_count: int = 0
    error: str | None = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _outcome_from_existing(existing: dict[str, Any], client_order_id: str) -> OrderOutcome:
    """Build an OrderOutcome from a GET /portfolio/orders response row."""
    status_raw = str(existing.get("status", "resting")).lower()
    # Kalshi returns statuses like "resting", "canceled", "executed", "pending".
    # Map anything we don't specifically recognise to the raw string — downstream
    # persistence layer stores it verbatim.
    status_map = {
        "executed": "filled",
        "filled": "filled",
        "resting": "resting",
        "canceled": "rejected",
        "cancelled": "rejected",
    }
    status = status_map.get(status_raw, status_raw)
    return OrderOutcome(
        client_order_id=client_order_id,
        order_id=existing.get("order_id"),
        status=status,
        filled_count=int(existing.get("filled_count_fp") or 0),
    )


class Executor:
    """Phase 4 executor — orchestrates risk check → persist → place → reconcile."""

    def __init__(
        self,
        client: KalshiClient,
        settings: Settings,
        risk: RiskManagerStub | RiskManager | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._risk = risk if risk is not None else RiskManagerStub()
        self._db = db_conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, intent: OrderIntent) -> OrderOutcome:
        """Full lifecycle: risk check → persist pending → place (paper|live) → update DB."""
        # (a) Risk check. KillSwitchActive must NEVER be caught inside this method.
        self._risk.check(intent)

        # (b) Generate client_order_id before any persistence or API call.
        client_order_id = uuid4().hex

        # (c) Persist intent with status='pending'.
        self._insert_pending(intent, client_order_id)

        # (d) Paper vs live.
        if not self._settings.LIVE_TRADING:
            logger.info(
                "paper_trade",
                client_order_id=client_order_id,
                ticker=intent.ticker,
                side=intent.side,
                action=intent.action,
                price=str(intent.price_dollars),
                count=intent.count,
            )
            outcome = OrderOutcome(client_order_id=client_order_id, status="paper")
            self._update_outcome(outcome, response=None)
            return outcome

        # (e) Live path.
        outcome = self._place_live(intent, client_order_id)
        # (f) Persistence of final outcome is handled inside _place_live via _update_outcome.
        return outcome

    def cancel(self, order_id: str) -> OrderOutcome:
        """Cancel a resting order by Kalshi order_id."""
        try:
            resp = self._client.cancel_order(order_id)
            order = resp.get("order") or {}
            coid = str(order.get("client_order_id", ""))
            return OrderOutcome(
                client_order_id=coid,
                order_id=order_id,
                status="rejected",
                filled_count=int(order.get("filled_count_fp") or 0),
            )
        except KalshiHTTPError as e:
            return OrderOutcome(
                client_order_id="",
                order_id=order_id,
                status="error",
                error=f"{e.code}: {e.msg}",
            )

    def cancel_all(self) -> list[OrderOutcome]:
        """Cancel every open order. Used by the kill switch path (Phase 5)."""
        try:
            resp = self._client.cancel_all()
        except KalshiHTTPError as e:
            return [OrderOutcome(client_order_id="", status="error", error=str(e))]
        orders = resp.get("orders") or []
        return [
            OrderOutcome(
                client_order_id=str(o.get("client_order_id", "")),
                order_id=o.get("order_id"),
                status="rejected",
                filled_count=int(o.get("filled_count_fp") or 0),
            )
            for o in orders
        ]

    def get_open_orders(self) -> list[dict[str, Any]]:
        resp = self._client.get_orders(status="resting")
        orders = resp.get("orders") or []
        return list(orders)

    # ------------------------------------------------------------------
    # Live placement with idempotent retry
    # ------------------------------------------------------------------

    def _place_live(self, intent: OrderIntent, client_order_id: str) -> OrderOutcome:
        body: dict[str, Any] = {
            "ticker": intent.ticker,
            "side": intent.side,
            "action": intent.action,
            "type": "limit",
            "yes_price_dollars": str(intent.price_dollars),
            "count_fp": intent.count,
            "time_in_force": intent.time_in_force,
            "post_only": intent.post_only,
            "client_order_id": client_order_id,
            "self_trade_prevention_type": "cancel_resting",
        }

        last_exc: Exception | None = None
        for attempt in range(self._settings.ORDER_RETRY_MAX_ATTEMPTS):
            try:
                resp = self._client.place_order(body)
                order = resp.get("order") or {}
                outcome = OrderOutcome(
                    client_order_id=client_order_id,
                    order_id=order.get("order_id"),
                    status=str(order.get("status", "resting")).lower(),
                    filled_count=int(order.get("filled_count_fp") or 0),
                )
                self._update_outcome(outcome, response=resp)
                return outcome

            except KalshiHTTPError as e:
                if e.code in _TERMINAL_REJECT_CODES:
                    outcome = OrderOutcome(
                        client_order_id=client_order_id,
                        status="rejected",
                        reject_code=e.code,
                        error=e.msg,
                    )
                    self._update_outcome(outcome, response=None)
                    return outcome
                if e.code == "ORDER_ALREADY_EXISTS":
                    existing = self._lookup_by_client_order_id(client_order_id)
                    if existing is not None:
                        outcome = _outcome_from_existing(existing, client_order_id)
                        self._update_outcome(outcome, response={"order": existing})
                        return outcome
                    # No record found — treat as error, do not retry (duplicate guard tripped).
                    outcome = OrderOutcome(
                        client_order_id=client_order_id,
                        status="error",
                        reject_code=e.code,
                        error=e.msg,
                    )
                    self._update_outcome(outcome, response=None)
                    return outcome
                if e.status >= 500:
                    last_exc = e
                    self._backoff(attempt)
                    continue
                # 4xx other than terminal/duplicate: re-raise, do not retry.
                raise

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                existing = self._lookup_by_client_order_id(client_order_id)
                if existing is not None:
                    outcome = _outcome_from_existing(existing, client_order_id)
                    self._update_outcome(outcome, response={"order": existing})
                    return outcome
                last_exc = e
                self._backoff(attempt)
                continue

        # Exhausted retries.
        if last_exc is None:
            last_exc = RuntimeError("Max retries exceeded")
        outcome = OrderOutcome(
            client_order_id=client_order_id,
            status="error",
            error=str(last_exc),
        )
        self._update_outcome(outcome, response=None)
        raise last_exc

    def _lookup_by_client_order_id(self, client_order_id: str) -> dict[str, Any] | None:
        """Best-effort GET to see if the order actually landed. Never raises."""
        try:
            resp = self._client.get_orders(client_order_id=client_order_id)
            orders = resp.get("orders") or []
            if orders:
                first = orders[0]
                return first if isinstance(first, dict) else None
            return None
        except Exception:  # noqa: BLE001 — reconciliation is best-effort
            return None

    def _backoff(self, attempt: int) -> None:
        base_ms = self._settings.ORDER_RETRY_BACKOFF_BASE_MS
        delay_ms = base_ms * (2 ** attempt) + random.randint(0, base_ms)
        time.sleep(delay_ms / 1000)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _insert_pending(self, intent: OrderIntent, client_order_id: str) -> None:
        if self._db is None:
            return
        request_body = {
            "ticker": intent.ticker,
            "side": intent.side,
            "action": intent.action,
            "yes_price_dollars": str(intent.price_dollars),
            "count_fp": intent.count,
            "time_in_force": intent.time_in_force,
            "post_only": intent.post_only,
            "client_order_id": client_order_id,
        }
        self._db.execute(
            """
            INSERT INTO orders (
                client_order_id, order_id, ticker, side, action,
                price_dollars, count, time_in_force, post_only,
                status, created_ts_ms, signal_module, my_probability,
                kelly_fraction, raw_request_json
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                client_order_id,
                intent.ticker,
                intent.side,
                intent.action,
                str(intent.price_dollars),
                intent.count,
                intent.time_in_force,
                1 if intent.post_only else 0,
                _now_ms(),
                intent.signal_module,
                None if intent.my_probability is None else str(intent.my_probability),
                None if intent.kelly_fraction is None else str(intent.kelly_fraction),
                json.dumps(request_body),
            ),
        )
        self._db.commit()

    def _update_outcome(
        self,
        outcome: OrderOutcome,
        response: dict[str, Any] | None,
    ) -> None:
        if self._db is None:
            return
        now = _now_ms()
        is_terminal = outcome.status in {"paper", "filled", "rejected", "error"}
        self._db.execute(
            """
            UPDATE orders
               SET order_id          = COALESCE(?, order_id),
                   status            = ?,
                   reject_code       = ?,
                   filled_count      = ?,
                   acked_ts_ms       = COALESCE(acked_ts_ms, ?),
                   terminal_ts_ms    = CASE WHEN ? THEN ? ELSE terminal_ts_ms END,
                   raw_response_json = ?
             WHERE client_order_id = ?
            """,
            (
                outcome.order_id,
                outcome.status,
                outcome.reject_code,
                outcome.filled_count,
                now,
                1 if is_terminal else 0,
                now,
                json.dumps(response) if response is not None else None,
                outcome.client_order_id,
            ),
        )
        self._db.commit()
