"""Seed the market universe (one-shot, for local dev)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config.settings import get_settings
from src.core.client import KalshiClient
from src.core.universe import UniverseFetcher
from src.storage.db import get_default_db

if __name__ == "__main__":
    settings = get_settings()
    conn = get_default_db()
    client = KalshiClient(settings)
    fetcher = UniverseFetcher(client)
    markets = fetcher.fetch_all()
    count = fetcher.upsert(conn, markets)
    print(f"Seeded {count} markets.")
    client.close()
    conn.close()
