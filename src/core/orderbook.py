"""LocalOrderbook — per-ticker in-memory book fed by Kalshi WS snapshot/delta messages.

Storage uses `SortedDict` with **negated price keys** so that iteration order
is best-bid-first (highest price first) without a custom comparator.

Thread-safe: a single `threading.Lock` wraps every apply/read. The WS thread
writes; scanner threads read. Lock contention is negligible at expected rates.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal

from sortedcontainers import SortedDict

from src.core.types import Orderbook, PriceLevel


class LocalOrderbook:
    """In-memory orderbook maintained from Kalshi WS snapshot + delta messages."""

    def __init__(self, ticker: str) -> None:
        self.ticker: str = ticker
        self.seq: int | None = None
        # keys are NEGATED Decimal prices so iter() yields best (highest) first.
        self._yes_bids: SortedDict = SortedDict()
        self._no_bids: SortedDict = SortedDict()
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply_snapshot(
        self,
        yes_levels: list[tuple[int, float]],
        no_levels: list[tuple[int, float]],
        seq: int | None,
    ) -> None:
        """Seed both sides from pre-parsed (price_cents, size) tuples.

        seq=None signals a REST-sourced resync where no WS sequence number
        is available yet; the next WS delta will establish the baseline.
        """
        with self._lock:
            self._yes_bids.clear()
            self._no_bids.clear()
            for price_cents, size in yes_levels:
                price = Decimal(price_cents) / Decimal(100)
                rounded = round(size)
                if rounded > 0:
                    self._yes_bids[-price] = rounded
            for price_cents, size in no_levels:
                price = Decimal(price_cents) / Decimal(100)
                rounded = round(size)
                if rounded > 0:
                    self._no_bids[-price] = rounded
            self.seq = seq

    def apply_delta(
        self,
        side: str,
        price_cents: int,
        delta: float,
        seq: int,
    ) -> Orderbook:
        """Apply a single price-level delta.

        Semantics:
        - Existing level: new_size = old + delta; drop if new_size <= 0.
        - New level: insert only when delta > 0 (size = delta).

        Gap detection is the caller's responsibility (see _on_delta in ws.py).
        """
        price = Decimal(price_cents) / Decimal(100)
        key = -price
        book = self._yes_bids if side == "yes" else self._no_bids
        with self._lock:
            existing = book.get(key)
            if existing is None:
                if delta > 0:
                    book[key] = round(delta)
            else:
                new_size = existing + delta
                if new_size <= 0:
                    del book[key]
                else:
                    book[key] = round(new_size)
            self.seq = seq
            return self._to_orderbook_locked()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def to_orderbook(self) -> Orderbook:
        """Return current state as an `Orderbook` dataclass."""
        with self._lock:
            return self._to_orderbook_locked()

    def _to_orderbook_locked(self) -> Orderbook:
        yes_bids = [PriceLevel(price=-k, size=v) for k, v in self._yes_bids.items()]
        no_bids = [PriceLevel(price=-k, size=v) for k, v in self._no_bids.items()]
        return Orderbook(
            ticker=self.ticker,
            seq=self.seq if self.seq is not None else 0,
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts_ms=int(time.time() * 1000),
        )

    def best_yes_bid(self) -> Decimal | None:
        with self._lock:
            if not self._yes_bids:
                return None
            return -next(iter(self._yes_bids))  # type: ignore[no-any-return]

    def best_no_bid(self) -> Decimal | None:
        with self._lock:
            if not self._no_bids:
                return None
            return -next(iter(self._no_bids))  # type: ignore[no-any-return]

    def yes_ask_impl(self) -> Decimal | None:
        """1.00 - best_no_bid. Returns None if no_bids is empty."""
        best_no = self.best_no_bid()
        if best_no is None:
            return None
        return Decimal("1") - best_no

    def mid_yes(self) -> Decimal | None:
        """(best_yes_bid + yes_ask_impl) / 2"""
        best_yes = self.best_yes_bid()
        ask_impl = self.yes_ask_impl()
        if best_yes is None or ask_impl is None:
            return None
        return (best_yes + ask_impl) / Decimal("2")

    def spread_cents(self) -> int | None:
        """int((yes_ask_impl - best_yes_bid) * 100) if both exist."""
        best_yes = self.best_yes_bid()
        ask_impl = self.yes_ask_impl()
        if best_yes is None or ask_impl is None:
            return None
        return int((ask_impl - best_yes) * 100)
