"""Core dataclasses for the Kalshi trading bot."""
from __future__ import annotations

from dataclasses import dataclass


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
