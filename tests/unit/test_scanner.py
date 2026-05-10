"""Unit tests for scanner detectors using fixture orderbooks."""
from __future__ import annotations

from decimal import Decimal

from src.core.scanner_rules import (
    detect_bracket_sum_arb,
    detect_thin_spread,
)
from src.core.types import Market, Orderbook, PriceLevel


def _make_market(
    ticker: str,
    event_ticker: str = "EVENT-001",
    volume_24h: int = 500,
    open_interest: int = 100,
) -> Market:
    return Market(
        ticker=ticker,
        event_ticker=event_ticker,
        series_ticker="TEST",
        category="other",
        title=None,
        subtitle=None,
        status="open",
        strike_type=None,
        floor_strike=None,
        cap_strike=None,
        tick_size="0.01",
        price_level_structure="linear_cent",
        open_time_ms=None,
        close_time_ms=9999999999000,
        latest_expiration_ms=None,
        settlement_source=None,
        volume_24h=volume_24h,
        open_interest=open_interest,
        last_price_cents=None,
        raw_json="{}",
    )


def _make_orderbook(ticker: str, yes_bid: str, no_bid: str, seq: int = 1) -> Orderbook:
    return Orderbook(
        ticker=ticker,
        seq=seq,
        yes_bids=[PriceLevel(price=Decimal(yes_bid), size=100)],
        no_bids=[PriceLevel(price=Decimal(no_bid), size=100)],
        ts_ms=1000000,
    )


# --- Bracket sum arb tests ---

def test_bracket_sum_arb_fires_on_deviation() -> None:
    """4-bucket event with YES bids summing to 0.95 → arb signal fires."""
    tickers = ["M1", "M2", "M3", "M4"]
    markets = [_make_market(t, event_ticker="EVT-001") for t in tickers]
    # YES bids: 0.25, 0.25, 0.25, 0.20 → sum = 0.95 → deviation = 5¢
    orderbooks = {
        "M1": _make_orderbook("M1", yes_bid="0.25", no_bid="0.74"),
        "M2": _make_orderbook("M2", yes_bid="0.25", no_bid="0.74"),
        "M3": _make_orderbook("M3", yes_bid="0.25", no_bid="0.74"),
        "M4": _make_orderbook("M4", yes_bid="0.20", no_bid="0.79"),
    }
    signals = detect_bracket_sum_arb("EVT-001", markets, orderbooks, min_deviation_cents=3)
    assert len(signals) == 4
    for s in signals:
        assert s.detector == "bracket_sum_arb"
        assert s.debug["deviation_cents"] == 5
        assert s.confidence > 0


def test_bracket_sum_arb_no_signal_when_sum_at_par() -> None:
    """6-bucket event summing to exactly 1.00 → no signal."""
    tickers = [f"M{i}" for i in range(6)]
    markets = [_make_market(t, event_ticker="EVT-002") for t in tickers]
    # Each YES bid = 1/6 ≈ 0.167, sum ≈ 1.00
    orderbooks = {
        t: _make_orderbook(t, yes_bid="0.167", no_bid="0.832")
        for t in tickers
    }
    signals = detect_bracket_sum_arb("EVT-002", markets, orderbooks, min_deviation_cents=3)
    assert signals == []


def test_bracket_sum_arb_no_signal_single_market() -> None:
    """Single market — cannot compute bracket sum."""
    markets = [_make_market("SOLO", event_ticker="EVT-003")]
    orderbooks = {"SOLO": _make_orderbook("SOLO", yes_bid="0.50", no_bid="0.49")}
    signals = detect_bracket_sum_arb("EVT-003", markets, orderbooks)
    assert signals == []


# --- Thin spread tests ---

def test_thin_spread_fires_on_wide_spread() -> None:
    """Market with 8¢ spread vs 2¢ category median → thin-spot signal."""
    market = _make_market("WIDE", volume_24h=500)
    # yes_bid=0.50, no_bid=0.42 → yes_ask_impl=0.58 → spread=8¢
    ob = _make_orderbook("WIDE", yes_bid="0.50", no_bid="0.42")
    signal = detect_thin_spread(market, ob, category_median_spread_cents=2.0, z_threshold=2.0)
    assert signal is not None
    assert signal.detector == "thin_spread"
    assert signal.debug["spread_cents"] == 8


def test_thin_spread_no_signal_normal_spread() -> None:
    """Market with 1¢ spread and 2¢ median → no signal (z < threshold)."""
    market = _make_market("NORM", volume_24h=500)
    ob = _make_orderbook("NORM", yes_bid="0.50", no_bid="0.49")
    # spread = 1¢
    signal = detect_thin_spread(market, ob, category_median_spread_cents=2.0, z_threshold=2.0)
    assert signal is None


def test_thin_spread_no_signal_low_volume() -> None:
    """Low volume market → filtered before z-score check."""
    market = _make_market("ILLIQ", volume_24h=50)
    ob = _make_orderbook("ILLIQ", yes_bid="0.50", no_bid="0.30")
    signal = detect_thin_spread(
        market, ob, category_median_spread_cents=2.0, z_threshold=2.0, min_volume_24h=200
    )
    assert signal is None


def test_thin_spread_zero_spread_returns_none() -> None:
    """yes_bid == yes_ask_impl (liquid book, zero spread) → None."""
    market = _make_market("TIGHT", volume_24h=500)
    # yes_bid=0.50, no_bid=0.50 → yes_ask_impl = 1 - 0.50 = 0.50 == best_yes
    ob = _make_orderbook("TIGHT", yes_bid="0.50", no_bid="0.50")
    signal = detect_thin_spread(market, ob, category_median_spread_cents=2.0, z_threshold=2.0)
    assert signal is None


def test_thin_spread_strict_cross_returns_none() -> None:
    """yes_bid > yes_ask_impl (truly crossed book) → None."""
    market = _make_market("CROSS", volume_24h=500)
    # yes_bid=0.55, no_bid=0.50 → yes_ask_impl = 1 - 0.50 = 0.50 < 0.55 = best_yes
    ob = _make_orderbook("CROSS", yes_bid="0.55", no_bid="0.50")
    signal = detect_thin_spread(market, ob, category_median_spread_cents=2.0, z_threshold=2.0)
    assert signal is None


def test_thin_spread_std_floor_fires_when_std_near_zero() -> None:
    """spread=2¢, category_median=0, std=0 → fires via std-floor path (not z-score)."""
    market = _make_market("STDFLOOR", volume_24h=500)
    # yes_bid=0.49, no_bid=0.49 → yes_ask_impl=0.51 → spread=2¢
    ob = _make_orderbook("STDFLOOR", yes_bid="0.49", no_bid="0.49")
    signal = detect_thin_spread(
        market,
        ob,
        category_median_spread_cents=0.0,
        category_std_spread_cents=0.0,
        z_threshold=2.0,
    )
    assert signal is not None
    assert signal.detector == "thin_spread"
    assert signal.debug["spread_cents"] == 2
