"""Kalshi bot entry point.

Paper mode is the default. Set LIVE_TRADING=true in .env to enable live trading;
the bot will print a warning and sleep 5 seconds so Ctrl-C can abort before
any live orders are placed.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config.settings import get_settings  # noqa: E402
from src.orchestrator.main import OrchestratorLoop  # noqa: E402


def main() -> None:
    settings = get_settings()
    if settings.LIVE_TRADING:
        print("=" * 60)
        print("WARNING: Running in LIVE mode — real orders will be placed.")
        print("Ctrl-C within 5 seconds to abort.")
        print("=" * 60)
        time.sleep(5)
    else:
        print("Running in PAPER mode (LIVE_TRADING=false).")

    OrchestratorLoop(settings).start()


if __name__ == "__main__":
    main()
