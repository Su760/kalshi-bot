"""Market universe fetcher and SQLite upsert logic."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from typing import Any

import structlog

from src.core.client import KalshiClient
from src.core.types import Market

logger = structlog.get_logger(__name__)

_WEATHER_PREFIXES = ("KXHIGH",)
_INDEX_PREFIXES = ("INX", "NASDAQ100")
_ECON_PREFIXES = ("FED", "CPI", "JOBS", "INFL", "GDP", "PCE", "PPI", "UNEMP")
_SPORTS_PREFIXES = ("KXNBA", "KXNFL", "KXMLB", "KXNHL", "KXNASCAR", "KXSOCCER", "KXMMA", "KXCFB")
_CRYPTO_PREFIXES = ("BTC", "ETH", "SOL", "CRYPTO")


def classify_category(market_data: dict[str, Any]) -> str:
    st: str = market_data.get("series_ticker", "")
    if any(st.startswith(p) for p in _WEATHER_PREFIXES):
        return "weather"
    if any(st.startswith(p) for p in _INDEX_PREFIXES):
        return "index"
    if any(st.startswith(p) for p in _ECON_PREFIXES):
        return "economics"
    if any(st.startswith(p) for p in _SPORTS_PREFIXES):
        return "sports"
    if any(st.startswith(p) for p in _CRYPTO_PREFIXES):
        return "crypto"
    return "other"


def parse_tick_size(market_data: dict[str, Any]) -> str:
    pls: str = market_data.get("price_level_structure", "")
    if pls == "linear_cent":
        return "0.01"
    if pls in ("deci_cent", "tapered_deci_cent"):
        return "0.001"
    logger.warning("unknown_price_level_structure", price_level_structure=pls, fallback="0.01")
    return "0.01"


def _iso_to_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return None


def _parse_market(raw: dict[str, Any]) -> Market:
    return Market(
        ticker=raw["ticker"],
        event_ticker=raw.get("event_ticker", ""),
        series_ticker=raw.get("series_ticker", ""),
        category=classify_category(raw),
        title=raw.get("title"),
        subtitle=raw.get("subtitle"),
        status=raw.get("status", ""),
        strike_type=raw.get("strike_type"),
        floor_strike=str(raw["floor_strike"]) if raw.get("floor_strike") is not None else None,
        cap_strike=str(raw["cap_strike"]) if raw.get("cap_strike") is not None else None,
        tick_size=parse_tick_size(raw),
        price_level_structure=raw.get("price_level_structure", "linear_cent"),
        open_time_ms=_iso_to_ms(raw.get("open_time")),
        close_time_ms=_iso_to_ms(raw.get("close_time")) or 0,
        latest_expiration_ms=_iso_to_ms(raw.get("expiration_time")),
        settlement_source=raw.get("settlement_source"),
        volume_24h=int(raw.get("volume_24h") or 0),
        open_interest=int(raw.get("open_interest") or 0),
        last_price_cents=raw.get("last_price"),
        raw_json=json.dumps(raw),
    )


class UniverseFetcher:
    def __init__(self, client: KalshiClient) -> None:
        self._client = client

    def fetch_all(self) -> list[Market]:
        markets: list[Market] = []
        cursor: str | None = None
        page = 0

        while True:
            resp = self._client.get_markets(status="open", limit=1000, cursor=cursor)
            raw_markets: list[dict[str, Any]] = resp.get("markets") or []
            for raw in raw_markets:
                try:
                    markets.append(_parse_market(raw))
                except Exception:
                    logger.exception("market_parse_error", ticker=raw.get("ticker"))

            cursor = resp.get("cursor") or None
            page += 1
            logger.info("universe_fetch_page", page=page, fetched=len(raw_markets), total=len(markets))

            if not cursor:
                break
            # Max 5 rps on this fetcher
            time.sleep(0.2)

        return markets

    def upsert(self, conn: sqlite3.Connection, markets: list[Market]) -> int:
        if not markets:
            return 0

        now_ms = int(time.time() * 1000)
        tickers = [m.ticker for m in markets]

        # Fetch existing first_seen_ms in one query
        placeholders = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"SELECT ticker, first_seen_ms FROM markets WHERE ticker IN ({placeholders})",
            tickers,
        ).fetchall()
        existing: dict[str, int] = {r["ticker"]: r["first_seen_ms"] for r in rows}

        conn.executemany(
            """
            INSERT OR REPLACE INTO markets (
                ticker, event_ticker, series_ticker, category, title, subtitle,
                status, strike_type, floor_strike, cap_strike,
                tick_size, price_level_structure,
                open_time_ms, close_time_ms, latest_expiration_ms, settlement_source,
                volume_24h, open_interest, last_price_cents,
                first_seen_ms, last_refreshed_ms, raw_json
            ) VALUES (
                :ticker, :event_ticker, :series_ticker, :category, :title, :subtitle,
                :status, :strike_type, :floor_strike, :cap_strike,
                :tick_size, :price_level_structure,
                :open_time_ms, :close_time_ms, :latest_expiration_ms, :settlement_source,
                :volume_24h, :open_interest, :last_price_cents,
                :first_seen_ms, :last_refreshed_ms, :raw_json
            )
            """,
            [
                {
                    "ticker": m.ticker,
                    "event_ticker": m.event_ticker,
                    "series_ticker": m.series_ticker,
                    "category": m.category,
                    "title": m.title,
                    "subtitle": m.subtitle,
                    "status": m.status,
                    "strike_type": m.strike_type,
                    "floor_strike": m.floor_strike,
                    "cap_strike": m.cap_strike,
                    "tick_size": m.tick_size,
                    "price_level_structure": m.price_level_structure,
                    "open_time_ms": m.open_time_ms,
                    "close_time_ms": m.close_time_ms,
                    "latest_expiration_ms": m.latest_expiration_ms,
                    "settlement_source": m.settlement_source,
                    "volume_24h": m.volume_24h,
                    "open_interest": m.open_interest,
                    "last_price_cents": m.last_price_cents,
                    "first_seen_ms": existing.get(m.ticker, now_ms),
                    "last_refreshed_ms": now_ms,
                    "raw_json": m.raw_json,
                }
                for m in markets
            ],
        )
        conn.commit()
        return len(markets)
