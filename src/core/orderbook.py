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
from typing import Any

from sortedcontainers import SortedDict

from src.core.types import Orderbook, PriceLevel


class LocalOrderbook:
    """In-memory orderbook maintained from Kalshi WS snapshot + delta messages."""

    def __init__(self, ticker: str) -> None:
        self.ticker: str = ticker
        self.seq: int = 0
        # keys are NEGATED Decimal prices so iter() yields best (highest) first.
        self._yes_bids: SortedDict = SortedDict()
        self._no_bids: SortedDict = SortedDict()
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply_snapshot(self, msg: dict[str, Any]) -> None:
        """Apply a full `orderbook_snapshot` WS message.

        Clears any prior state and reseeds both sides from the snapshot.
        """
        m = msg["msg"]
        with self._lock:
            self._yes_bids.clear()
            self._no_bids.clear()
            for entry in m.get("yes", []):
                price = Decimal(str(entry[0]))
                size = int(entry[1])
                if size > 0:
                    self._yes_bids[-price] = size
            for entry in m.get("no", []):
                price = Decimal(str(entry[0]))
                size = int(entry[1])
                if size > 0:
                    self._no_bids[-price] = size
            self.seq = int(m["seq"])

    def apply_delta(self, msg: dict[str, Any]) -> Orderbook | None:
        """Apply an `orderbook_delta` WS message.

        Returns an `Orderbook` snapshot after applying, or `None` on seq gap.
        On gap we do NOT mutate state; the caller triggers REST resync.
        """
        m = msg["msg"]
        msg_seq = int(m["seq"])
        with self._lock:
            if msg_seq != self.seq + 1:
                return None
            price = Decimal(str(m["price"]))
            delta = int(m["delta"])
            side = m["side"]
            book = self._yes_bids if side == "yes" else self._no_bids
            key = -price
            existing = book.get(key, 0)
            new_size = existing + delta
            if new_size <= 0:
                book.pop(key, None)
            else:
                book[key] = new_size
            self.seq = msg_seq
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
            seq=self.seq,
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
