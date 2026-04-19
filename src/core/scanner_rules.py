"""Pure detector functions for the +EV scanner.

Each function is side-effect-free. Input is a Market + LocalOrderbook snapshot.
Output is a SubSignal (probability estimate + confidence + debug dict) or None.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.core.types import Market, Orderbook


@dataclass
class SubSignal:
    my_probability: float    # [0, 1] YES probability estimate
    confidence: float        # [0, 1]
    detector: str            # which detector fired
    debug: dict[str, Any]    # free-form context for logging


def detect_bracket_sum_arb(
    event_ticker: str,
    markets: list[Market],
    orderbooks: dict[str, Orderbook],
    min_deviation_cents: int = 3,
) -> list[SubSignal]:
    """
    Bracket sum arbitrage detector.

    For a set of mutually exclusive + collectively exhaustive YES contracts
    (one event, multiple bracket outcomes), the sum of best YES bids should
    equal $1.00. Deviation = systematic mispricing.

    If sum < 1.00 by >= min_deviation_cents: all YES sides are cheap → buy signal.
    If sum > 1.00: all YES sides are expensive → sell signal (not implemented yet).

    Returns one SubSignal per market in the bracket if arb exists, else [].
    """
    if len(markets) < 2:
        return []

    best_bids: dict[str, Decimal] = {}
    for m in markets:
        ob = orderbooks.get(m.ticker)
        if ob is None or not ob.yes_bids:
            return []  # incomplete book — can't compute sum
        best_bids[m.ticker] = ob.yes_bids[0].price

    total = sum(best_bids.values())
    deviation_cents = int((Decimal("1") - total) * 100)

    if deviation_cents < min_deviation_cents:
        return []

    confidence = min(1.0, float(deviation_cents) / 10)  # 10¢ deviation = full confidence

    signals = []
    for m in markets:
        best_bid = best_bids[m.ticker]
        my_prob = float(best_bid) / float(total) if float(total) > 0 else 1.0 / len(markets)
        my_prob = max(0.01, min(0.99, my_prob))
        signals.append(SubSignal(
            my_probability=my_prob,
            confidence=confidence,
            detector="bracket_sum_arb",
            debug={
                "event_ticker": event_ticker,
                "market_ticker": m.ticker,
                "bracket_sum": float(total),
                "deviation_cents": deviation_cents,
                "best_bid": float(best_bid),
            },
        ))
    return signals


def detect_thin_spread(
    market: Market,
    orderbook: Orderbook,
    category_median_spread_cents: float,
    z_threshold: float = 2.0,
    min_volume_24h: int = 200,
) -> SubSignal | None:
    """
    Liquidity thin-spot detector.

    A market with an abnormally wide spread (z-score > threshold) relative
    to its category median may offer edge to passive limit orders.

    Returns a SubSignal at the mid-price if the spread is anomalous.
    """
    if market.volume_24h < min_volume_24h:
        return None
    if not orderbook.yes_bids or not orderbook.no_bids:
        return None

    best_yes = orderbook.yes_bids[0].price
    best_no = orderbook.no_bids[0].price
    yes_ask_impl = Decimal("1") - best_no

    if yes_ask_impl <= best_yes:
        return None  # crossed book — data issue

    spread_cents = int((yes_ask_impl - best_yes) * 100)

    if category_median_spread_cents <= 0:
        return None

    z_score = (spread_cents - category_median_spread_cents) / max(1.0, category_median_spread_cents * 0.5)

    if z_score < z_threshold:
        return None

    mid = float((best_yes + yes_ask_impl) / Decimal("2"))
    confidence = min(1.0, (z_score - z_threshold) / 3.0)

    return SubSignal(
        my_probability=mid,
        confidence=confidence,
        detector="thin_spread",
        debug={
            "spread_cents": spread_cents,
            "category_median_spread_cents": category_median_spread_cents,
            "z_score": round(z_score, 2),
            "mid": round(mid, 4),
        },
    )


def detect_stale_quote(
    market: Market,
    orderbook: Orderbook,
    last_trade_ms: int | None,
    correlated_mid: float | None,
    now_ms: int,
    stale_threshold_ms: int = 600_000,  # 10 minutes
) -> SubSignal | None:
    """
    Stale quote detector.

    If a market hasn't traded in stale_threshold_ms and a correlated market
    in the same event has moved, the stale book may lag true probability.

    correlated_mid: mid-price of the most-traded market in the same event.
    """
    if last_trade_ms is None:
        return None
    if correlated_mid is None:
        return None
    if not orderbook.yes_bids or not orderbook.no_bids:
        return None

    age_ms = now_ms - last_trade_ms
    if age_ms < stale_threshold_ms:
        return None

    best_yes = orderbook.yes_bids[0].price
    best_no = orderbook.no_bids[0].price
    yes_ask_impl = Decimal("1") - best_no
    mid = float((best_yes + yes_ask_impl) / Decimal("2"))

    divergence = abs(correlated_mid - mid)
    if divergence < 0.05:  # less than 5 cents divergence — not worth it
        return None

    confidence = min(1.0, divergence * 5)  # 20¢ divergence = full confidence

    return SubSignal(
        my_probability=correlated_mid,  # lean toward the liquid market's price
        confidence=confidence * 0.5,   # half confidence — indirect signal
        detector="stale_quote",
        debug={
            "age_ms": age_ms,
            "mid": round(mid, 4),
            "correlated_mid": round(correlated_mid, 4),
            "divergence": round(divergence, 4),
        },
    )
