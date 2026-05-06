"""Unit tests for LocalOrderbook snapshot/delta apply."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from src.core.orderbook import LocalOrderbook

FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "orderbook_delta_sequence.json"
)


def _parse_levels(rows: list[list[str]]) -> list[tuple[int, float]]:
    return [(round(float(p) * 100), float(s)) for p, s in rows]


def test_orderbook_apply_sequence() -> None:
    data = json.loads(FIXTURE.read_text())
    book = LocalOrderbook(data["ticker"])

    snap = data["initial_snapshot"]
    book.apply_snapshot(
        _parse_levels(snap["yes_dollars"]),
        _parse_levels(snap["no_dollars"]),
        seq=snap["seq"],
    )

    for d in data["deltas"]:
        price_cents = round(float(d["price_dollars"]) * 100)
        book.apply_delta(d["side"], price_cents, float(d["delta_fp"]), d["seq"])

    expected = data["expected_final_state"]
    assert str(book.best_yes_bid()) == expected["best_yes_bid"]
    assert str(book.best_no_bid()) == expected["best_no_bid"]
    assert str(book.yes_ask_impl()) == expected["yes_ask_impl"]
    assert book.spread_cents() == expected["spread_cents"]

    ob = book.to_orderbook()
    assert ob.seq == 104
    assert len(ob.yes_bids) == 3
    assert len(ob.no_bids) == 1


def test_apply_delta_new_level_ignored_when_negative() -> None:
    """A negative delta for a price level that doesn't exist is ignored."""
    book = LocalOrderbook("TEST")
    book.apply_snapshot([(50, 10.0)], [(49, 10.0)], seq=100)
    book.apply_delta("yes", 51, -5.0, seq=101)  # non-existent level, negative
    assert book.best_yes_bid() == Decimal("0.50")  # unchanged


def test_apply_delta_drops_level_at_zero() -> None:
    """Delta reducing size to zero removes the price level."""
    book = LocalOrderbook("TEST")
    book.apply_snapshot([(50, 10.0)], [(49, 10.0)], seq=100)
    book.apply_delta("yes", 50, -10.0, seq=101)
    assert book.best_yes_bid() is None


def test_yes_ask_impl_is_one_minus_best_no_bid() -> None:
    book = LocalOrderbook("TEST")
    book.apply_snapshot([(60, 10.0)], [(35, 10.0)], seq=1)
    assert book.yes_ask_impl() == Decimal("0.65")  # 1.00 - 0.35


def test_apply_snapshot_with_none_seq_leaves_seq_none() -> None:
    """REST resync sets seq=None; first WS delta then sets it."""
    book = LocalOrderbook("TEST")
    book.apply_snapshot([(50, 10.0)], [(49, 10.0)], seq=None)
    assert book.seq is None
    # First delta accepted as baseline regardless of seq value
    book.apply_delta("yes", 50, 5.0, seq=201)
    assert book.seq == 201
