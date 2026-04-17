"""Core dataclasses for the Kalshi trading bot."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Market:
    ticker: str
    event_ticker: str
    series_ticker: str
    category: str
    title: str | None
    subtitle: str | None
    status: str
    strike_type: str | None
    floor_strike: str | None
    cap_strike: str | None
    tick_size: str
    price_level_structure: str
    open_time_ms: int | None
    close_time_ms: int
    latest_expiration_ms: int | None
    settlement_source: str | None
    volume_24h: int
    open_interest: int
    last_price_cents: int | None
    raw_json: str


@dataclass
class PriceLevel:
    price: Decimal
    size: int  # count_fp as integer


@dataclass
class Orderbook:
    ticker: str
    seq: int
    yes_bids: list[PriceLevel]  # sorted best->worst (descending price)
    no_bids: list[PriceLevel]   # sorted best->worst (descending price)
    ts_ms: int


@dataclass
class Trade:
    trade_id: str
    ticker: str
    ts_ms: int
    side: str       # 'yes' | 'no'
    action: str     # 'buy' | 'sell'
    yes_price: str  # decimal string, use yes_price_dollars field
    count: int      # use count_fp field
    is_our_fill: bool
