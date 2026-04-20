"""WS collector — grabs first 50 tickers regardless of volume."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config.settings import get_settings
from src.core.client import KalshiClient
from src.core.ws import KalshiWebSocket
from src.storage.db import get_default_db

settings = get_settings()
client = KalshiClient(settings)
conn = get_default_db()
rows = conn.execute("SELECT ticker FROM markets LIMIT 50").fetchall()
tickers = [r[0] for r in rows]
conn.close()

print(f"Subscribing to {len(tickers)} tickers...")
print(f"Sample: {tickers[:3]}")
ws = KalshiWebSocket(settings, client, tickers=tickers)
ws.start()
print("WS running. Ctrl+C to stop.")
try:
    while True:
        time.sleep(10)
        print(f"Reconnects: {ws.reconnects_total}")
except KeyboardInterrupt:
    ws.stop()
    print("Stopped.")
