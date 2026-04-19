"""Known-answer tests for Kelly sizing."""
from __future__ import annotations

from decimal import Decimal

from src.core.sizing import kelly_contracts, net_edge


def test_kelly_positive_edge_returns_nonzero() -> None:
    # p=0.60, market=0.50, bankroll=$1000, 0.25x Kelly
    contracts = kelly_contracts(
        my_prob=0.60,
        market_price=Decimal("0.50"),
        bankroll_dollars=Decimal("1000"),
        kelly_fraction=0.25,
        max_contracts=100,
    )
    assert contracts > 0


def test_kelly_no_edge_returns_zero() -> None:
    # p=0.50, market=0.50 — no edge
    contracts = kelly_contracts(
        my_prob=0.50,
        market_price=Decimal("0.50"),
        bankroll_dollars=Decimal("1000"),
        kelly_fraction=0.25,
    )
    assert contracts == 0


def test_kelly_negative_edge_returns_zero() -> None:
    contracts = kelly_contracts(
        my_prob=0.40,
        market_price=Decimal("0.55"),
        bankroll_dollars=Decimal("1000"),
        kelly_fraction=0.25,
    )
    assert contracts == 0


def test_kelly_respects_max_contracts() -> None:
    # Huge edge, huge bankroll — should be capped
    contracts = kelly_contracts(
        my_prob=0.95,
        market_price=Decimal("0.50"),
        bankroll_dollars=Decimal("100000"),
        kelly_fraction=0.25,
        max_contracts=50,
    )
    assert contracts <= 50


def test_net_edge_positive() -> None:
    # p=0.60, price=0.50, maker fee on 1 contract at 0.50 = $0.01
    # net = 0.60 - 0.50 - 0.01 = 0.09
    edge = net_edge(0.60, Decimal("0.50"), is_maker=True)
    assert edge > 0
    assert abs(edge - 0.09) < 0.001


def test_net_edge_negative_after_fee() -> None:
    # p=0.508, price=0.50 — gross edge 0.8¢ < maker fee 1¢ → net negative
    edge = net_edge(0.508, Decimal("0.50"), is_maker=True)
    assert edge < 0
