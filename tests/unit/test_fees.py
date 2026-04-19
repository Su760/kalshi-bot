"""Known-answer tests for Kalshi fee formulas."""
from __future__ import annotations

from decimal import Decimal

from src.core.sizing import kalshi_maker_fee, kalshi_taker_fee


def test_taker_fee_at_50_cents_100_contracts() -> None:
    # 0.07 * 100 * 0.50 * 0.50 = 1.75 — exactly on cent boundary
    fee = kalshi_taker_fee(100, Decimal("0.50"))
    assert fee == Decimal("1.75")


def test_maker_fee_at_50_cents_100_contracts() -> None:
    # 0.0175 * 100 * 0.50 * 0.50 = 0.4375 → ceil to 0.44
    fee = kalshi_maker_fee(100, Decimal("0.50"))
    assert fee == Decimal("0.44")


def test_taker_fee_ceil_to_cent() -> None:
    # 0.07 * 1 * 0.50 * 0.50 = 0.0175 → ceil to 0.02
    fee = kalshi_taker_fee(1, Decimal("0.50"))
    assert fee == Decimal("0.02")


def test_maker_fee_single_contract() -> None:
    # 0.0175 * 1 * 0.50 * 0.50 = 0.004375 → ceil to 0.01
    fee = kalshi_maker_fee(1, Decimal("0.50"))
    assert fee == Decimal("0.01")


def test_fee_symmetric_around_50() -> None:
    # Fee should be same at 0.40 and 0.60 (P*(1-P) is symmetric)
    fee_40 = kalshi_taker_fee(100, Decimal("0.40"))
    fee_60 = kalshi_taker_fee(100, Decimal("0.60"))
    assert fee_40 == fee_60
