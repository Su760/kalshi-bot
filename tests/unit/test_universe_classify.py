from unittest.mock import MagicMock

import pytest

from src.core.universe import MAX_MARKETS_FETCH, UniverseFetcher, classify_category


@pytest.mark.parametrize("series_ticker,expected", [
    ("KXHIGHNY", "weather"),
    ("KXHIGHCHI", "weather"),
    ("INX", "index"),
    ("NASDAQ100", "index"),
    ("FED-RATE", "economics"),
    ("CPI-JUN", "economics"),
    ("JOBS-MAR", "economics"),
    ("KXNBA-FINALS", "sports"),
    ("KXNFL-SB", "sports"),
    ("KXMLB-WS", "sports"),
    ("BTC-USD", "crypto"),
    ("ETH-PRICE", "crypto"),
    ("PRES-2024", "other"),
    ("SCOTUS-ROE", "other"),
])
def test_classify_category(series_ticker: str, expected: str) -> None:
    market_data = {"series_ticker": series_ticker}
    assert classify_category(market_data) == expected


def test_fetch_all_hard_cap() -> None:
    client = MagicMock()
    # Each call returns 1000 markets with a next cursor — infinite without cap
    client.get_markets.return_value = {
        "markets": [{"ticker": f"T-{i}"} for i in range(1000)],
        "cursor": "next",
    }
    fetcher = UniverseFetcher(client)
    markets = fetcher.fetch_all()
    assert len(markets) <= MAX_MARKETS_FETCH + 1000
    assert client.get_markets.call_count <= MAX_MARKETS_FETCH // 1000 + 1
