"""Fee-adjusted Kelly criterion sizing for Kalshi binary contracts."""
from __future__ import annotations

import math
from decimal import Decimal

TAKER_FEE_MULT = Decimal("0.07")
MAKER_FEE_MULT = Decimal("0.0175")
INDEX_TAKER_FEE_MULT = Decimal("0.035")


def kalshi_taker_fee(contracts: int, price: Decimal) -> Decimal:
    """
    Fee = ceil_to_cent(0.07 × C × P × (1−P))
    Price is in dollars [0, 1]. Returns fee in dollars.
    For S&P/Nasdaq index markets use INDEX_TAKER_FEE_MULT instead.
    """
    raw = TAKER_FEE_MULT * Decimal(contracts) * price * (Decimal("1") - price)
    cents = math.ceil(float(raw) * 100)
    return Decimal(cents) / Decimal(100)


def kalshi_maker_fee(contracts: int, price: Decimal) -> Decimal:
    """Fee = ceil_to_cent(0.0175 × C × P × (1−P)). Charged only on fills."""
    raw = MAKER_FEE_MULT * Decimal(contracts) * price * (Decimal("1") - price)
    cents = math.ceil(float(raw) * 100)
    return Decimal(cents) / Decimal(100)


def kelly_contracts(
    my_prob: float,
    market_price: Decimal,
    bankroll_dollars: Decimal,
    kelly_fraction: float = 0.25,
    max_contracts: int = 100,
    is_maker: bool = True,
) -> int:
    """
    Fee-adjusted Kelly sizing for a Kalshi YES binary contract.

    Returns the number of contracts to buy (0 if no edge after fees).

    Kelly formula for binary bet:
        f = (p*(1-c) - (1-p)*c) / (c*(1-c))
    where:
        p = my probability of YES
        c = market price of YES (cost per contract in dollars)

    Args:
        my_prob: my estimated probability of YES [0, 1]
        market_price: current best ask for YES in dollars [0, 1]
        bankroll_dollars: total account equity in dollars
        kelly_fraction: fraction of full Kelly to use (default 0.25)
        max_contracts: hard cap on position size
        is_maker: if True use maker fee, else taker fee
    """
    c = float(market_price)
    p = my_prob

    if c <= 0 or c >= 1:
        return 0

    edge = p * (1 - c) - (1 - p) * c
    if edge <= 0:
        return 0

    full_kelly_fraction = edge / (c * (1 - c))
    sized_fraction = full_kelly_fraction * kelly_fraction

    dollar_bet = float(bankroll_dollars) * sized_fraction
    contracts_raw = dollar_bet / c
    contracts = int(contracts_raw)
    contracts = max(0, min(contracts, max_contracts))

    price_dec = market_price
    fee = kalshi_maker_fee(1, price_dec) if is_maker else kalshi_taker_fee(1, price_dec)
    net_payout = Decimal("1") - price_dec - fee
    if float(net_payout) <= 0:
        return 0

    return contracts


def net_edge(
    my_prob: float,
    market_price: Decimal,
    is_maker: bool = True,
) -> float:
    """
    Net edge after fee for a single contract.
    Returns (my_prob - market_price - fee_per_contract) as a float.
    Positive means profitable in expectation.
    """
    c = market_price
    fee = kalshi_maker_fee(1, c) if is_maker else kalshi_taker_fee(1, c)
    return my_prob - float(c) - float(fee)
