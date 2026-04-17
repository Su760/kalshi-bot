import pytest

from src.core.universe import classify_category


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
