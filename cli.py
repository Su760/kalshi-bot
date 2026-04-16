"""Kalshi trading bot CLI — Phase 0: health subcommand only."""

from __future__ import annotations

import time
import traceback
from email.utils import parsedate_to_datetime

import httpx
import typer
from rich.console import Console

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def health() -> None:
    """Verify connectivity, auth, and clock skew against Kalshi demo."""
    try:
        from src.config.settings import get_settings

        settings = get_settings()
    except Exception as exc:
        msg = str(exc)
        if "KALSHI_API_KEY_ID" in msg or "field required" in msg.lower():
            console.print("Missing required env var: KALSHI_API_KEY_ID", style="red")
        else:
            console.print(f"Config error: {msg}", style="red")
        raise typer.Exit(1) from None

    try:
        from src.core.auth import load_private_key

        load_private_key(settings.KALSHI_PRIVATE_KEY_PATH)
    except FileNotFoundError:
        console.print(
            f"Private key not found at {settings.KALSHI_PRIVATE_KEY_PATH}", style="red"
        )
        raise typer.Exit(1) from None

    try:
        from src.core.client import KalshiAuthError, KalshiClient, KalshiClockSkewError

        with KalshiClient(settings) as client:
            try:
                client.get_exchange_status()
            except KalshiClockSkewError as exc:
                skew_ms = str(exc).split()[2].rstrip("ms")
                console.print(
                    f"Clock skew too high: {skew_ms}ms (max 2000ms). "
                    "Run `sudo chronyd -q` or equivalent.",
                    style="red",
                )
                raise typer.Exit(1) from exc
            except KalshiAuthError as exc:
                console.print(
                    "Authentication failed. Check KALSHI_API_KEY_ID and PEM "
                    "match the same Kalshi account.",
                    style="red",
                )
                raise typer.Exit(1) from exc

            # Measure clock skew from a raw unauthenticated call
            response = httpx.get(
                f"{settings.KALSHI_REST_BASE_URL}/exchange/status", timeout=10.0
            )
            date_header = response.headers.get("Date", "")
            if date_header:
                server_dt = parsedate_to_datetime(date_header)
                server_ms = int(server_dt.timestamp() * 1000)
                local_ms = int(time.time() * 1000)
                clock_skew_ms = abs(local_ms - server_ms)
            else:
                clock_skew_ms = -1

            balance_data = client.get_balance()
            balance_cents = balance_data.get("balance", 0)

    except typer.Exit:
        raise
    except Exception as exc:
        traceback.print_exc()
        console.print(f"\nstatus=FAIL: {exc}", style="red")
        raise typer.Exit(1) from exc

    console.print(f"env={settings.KALSHI_ENV}")
    console.print(f"base_url={settings.KALSHI_REST_BASE_URL}")
    console.print(f"clock_skew_ms={clock_skew_ms}")
    console.print(f"balance_cents={balance_cents}")
    console.print("status=OK", style="green")


if __name__ == "__main__":
    app()
