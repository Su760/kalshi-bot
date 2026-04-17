"""Unit tests for LocalOrderbook snapshot/delta apply and seq-gap detection."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from src.core.orderbook import LocalOrderbook

FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "orderbook_delta_sequence.json"
)


def test_orderbook_apply_sequence() -> None:
    data = json.loads(FIXTURE.read_text())
    book = LocalOrderbook(data["ticker"])

    for msg in data["messages"]:
        if msg["type"] == "orderbook_snapshot":
            book.apply_snapshot(msg)
        elif msg["type"] == "orderbook_delta":
            result = book.apply_delta(msg)
            assert result is not None, f"Unexpected seq gap at seq {msg['msg']['seq']}"

    expected = data["expected_final_state"]
    assert str(book.best_yes_bid()) == expected["best_yes_bid"]
    assert str(book.best_no_bid()) == expected["best_no_bid"]
    assert str(book.yes_ask_impl()) == expected["yes_ask_impl"]
    assert book.spread_cents() == expected["spread_cents"]

    ob = book.to_orderbook()
    assert ob.seq == 104
    assert len(ob.yes_bids) == 3
    assert len(ob.no_bids) == 1


def test_orderbook_seq_gap_returns_none() -> None:
    book = LocalOrderbook("TEST-MARKET-0001")
    book.apply_snapshot({
        "type": "orderbook_snapshot",
        "msg": {
            "market_ticker": "TEST-MARKET-0001",
            "seq": 100,
            "yes": [["0.50", 10]],
            "no": [["0.49", 10]],
        },
    })
    # Skip seq 101 — apply 102 directly → should return None (gap)
    result = book.apply_delta({
        "type": "orderbook_delta",
        "msg": {
            "market_ticker": "TEST-MARKET-0001",
            "side": "yes",
            "price": "0.51",
            "delta": 5,
            "seq": 102,
        },
    })
    assert result is None
    # Gap must not have mutated state.
    assert book.seq == 100
    assert book.best_yes_bid() == Decimal("0.50")


def test_yes_ask_impl_is_one_minus_best_no_bid() -> None:
    book = LocalOrderbook("TEST")
    book.apply_snapshot({
        "type": "orderbook_snapshot",
        "msg": {
            "market_ticker": "TEST",
            "seq": 1,
            "yes": [["0.60", 10]],
            "no": [["0.35", 10]],
        },
    })
    assert book.yes_ask_impl() == Decimal("0.65")  # 1.00 - 0.35
