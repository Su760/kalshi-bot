"""Core +EV scanner — market-agnostic signal module.

Implements the SignalModule protocol. Aggregates signals from pure detector
functions in scanner_rules.py. Every market category is in scope.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

import structlog

from src.core.orderbook import LocalOrderbook
from src.core.scanner_rules import (
    SubSignal,
    detect_bracket_sum_arb,
    detect_thin_spread,
)
from src.core.sizing import net_edge
from src.core.types import Market, Orderbook
from src.modules.base import Signal

logger = structlog.get_logger(__name__)

MIN_EDGE_PCT = 0.08
MIN_NET_EDGE_PCT = 0.02
MIN_VOLUME_24H = 0
MIN_OPEN_INTEREST = 0
BRACKET_SUM_MIN_DEVIATION_CENTS = 3
SPREAD_Z_THRESHOLD = 2.0


class Scanner:
    """Market-agnostic +EV scanner.

    Usage:
        scanner = Scanner(live_books=live_books)
        signal = scanner.predict(market, now=datetime.utcnow())
    """

    name: str = "scanner"
    enabled: bool = True

    def __init__(
        self,
        live_books: dict[str, LocalOrderbook],
        markets_by_event: dict[str, list[Market]] | None = None,
        category_medians: dict[str, float] | None = None,
    ) -> None:
        """
        Args:
            live_books: ticker → LocalOrderbook (from KalshiWebSocket)
            markets_by_event: event_ticker → list of markets (for bracket arb)
            category_medians: category → median spread in cents (for thin-spot)
        """
        self._books = live_books
        self._markets_by_event: dict[str, list[Market]] = markets_by_event or {}
        self._category_medians: dict[str, float] = category_medians or {}

    def applies_to(self, market: Market) -> bool:
        """Scanner applies to every market with sufficient liquidity."""
        return (
            market.status in ("active", "open")
            and market.volume_24h >= MIN_VOLUME_24H
            and market.open_interest >= MIN_OPEN_INTEREST
        )

    def predict(self, market: Market, now: datetime) -> Signal | None:
        """Aggregate all sub-detector signals, return highest-confidence or None."""
        book = self._books.get(market.ticker)
        if book is None:
            logger.debug("scanner_skip", ticker=market.ticker, reason="no_book")
            return None

        logger.debug(
            "scanner_book_state",
            ticker=market.ticker,
            seq=book.seq,
            yes_levels_in_book=len(book._yes_bids),
            no_levels_in_book=len(book._no_bids),
        )
        ob: Orderbook = book.to_orderbook()
        if not ob.yes_bids or not ob.no_bids:
            logger.debug(
                "scanner_skip",
                ticker=market.ticker,
                reason="no_bids",
                has_yes_bids=bool(ob.yes_bids),
                has_no_bids=bool(ob.no_bids),
                yes_bids_len=len(ob.yes_bids) if ob.yes_bids is not None else None,
                no_bids_len=len(ob.no_bids) if ob.no_bids is not None else None,
                yes_bids_type=type(ob.yes_bids).__name__,
                no_bids_type=type(ob.no_bids).__name__,
            )
            return None

        sub_signals: list[SubSignal] = []

        # --- Detector 1: bracket sum arb ---
        event_markets = self._markets_by_event.get(market.event_ticker, [])
        if len(event_markets) >= 2:
            event_obs: dict[str, Orderbook] = {}
            for m in event_markets:
                b = self._books.get(m.ticker)
                if b is not None:
                    event_obs[m.ticker] = b.to_orderbook()
            arb_signals = detect_bracket_sum_arb(
                event_ticker=market.event_ticker,
                markets=event_markets,
                orderbooks=event_obs,
                min_deviation_cents=BRACKET_SUM_MIN_DEVIATION_CENTS,
            )
            for s in arb_signals:
                if s.debug.get("market_ticker") == market.ticker:
                    sub_signals.append(s)

        # --- Detector 2: thin spread ---
        _spreads: dict[str, list[float]] = defaultdict(list)
        for _ticker, _bk in self._books.items():
            _snap = _bk.to_orderbook()
            if _snap.yes_bids and _snap.no_bids:
                _sp = (1.0 - float(_snap.no_bids[0].price)) - float(_snap.yes_bids[0].price)
                if _sp > 0:
                    _spreads["all"].append(_sp)
        _cat_medians: dict[str, float] = {}
        _cat_stds: dict[str, float] = {}
        for _cat, _sps in _spreads.items():
            _sps.sort()
            _cat_medians[_cat] = (_sps[len(_sps) // 2] if _sps else 0.05) * 100
            _cat_stds[_cat] = (statistics.pstdev(_sps) if _sps else 0.0) * 100
        if not _cat_medians:
            _cat_medians = {"all": 5.0}
            _cat_stds = {"all": 1.0}
        category_median = _cat_medians.get(market.category) or _cat_medians.get("all", 5.0)
        category_std = _cat_stds.get(market.category) or _cat_stds.get("all", 1.0)
        thin = detect_thin_spread(
            market=market,
            orderbook=ob,
            category_median_spread_cents=category_median,
            category_std_spread_cents=category_std,
            z_threshold=SPREAD_Z_THRESHOLD,
            min_volume_24h=MIN_VOLUME_24H,
        )
        if thin is not None:
            sub_signals.append(thin)

        if not sub_signals:
            logger.debug("scanner_skip", ticker=market.ticker, reason="no_sub_signals")
            return None

        best = max(sub_signals, key=lambda s: s.confidence)

        best_yes = ob.yes_bids[0].price
        yes_ask = Decimal("1") - ob.no_bids[0].price
        market_mid = float((best_yes + yes_ask) / Decimal("2"))

        raw_edge = abs(best.my_probability - market_mid)
        if raw_edge < MIN_EDGE_PCT:
            logger.debug(
                "scanner_skip",
                ticker=market.ticker,
                reason="edge_below_threshold",
                raw_edge=round(raw_edge, 4),
                min_edge=MIN_EDGE_PCT,
            )
            return None

        net = net_edge(
            my_prob=best.my_probability,
            market_price=Decimal(str(market_mid)),
            is_maker=True,
        )
        if net < MIN_NET_EDGE_PCT:
            logger.debug(
                "scanner_skip",
                ticker=market.ticker,
                reason="net_edge_below_threshold",
                net_edge=round(net, 4),
                min_net_edge=MIN_NET_EDGE_PCT,
            )
            return None

        return Signal(
            my_probability=best.my_probability,
            confidence=best.confidence,
            data_freshness_seconds=0,
            source_module="scanner",
            debug={
                "detector": best.detector,
                "market_mid": round(market_mid, 4),
                "raw_edge": round(raw_edge, 4),
                "net_edge": round(net, 4),
                **best.debug,
            },
        )
