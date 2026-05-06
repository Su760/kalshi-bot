# Kalshi REST client — hand-rolled.
#
# Decision log: We use the official Kalshi starter code
# (github.com/Kalshi/kalshi-starter-code-python) as the signing reference
# only. We do NOT depend on kalshi-python or pykalshi because the Master
# Build Plan specifies our own rate limiter (15 rps token bucket), retry
# classification, idempotency pattern (client_order_id lookup-before-retry),
# logging shape, and orderbook manager. Hand-rolling gives clean seams for
# those later phases. -- Phase 0

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import structlog

from src.config.constants import CLIENT_READ_RPS, MAX_CLOCK_SKEW_MS
from src.config.settings import Settings
from src.core.auth import build_headers, load_private_key

logger = structlog.get_logger(__name__)

class KalshiAuthError(Exception):
    """Raised on 401/403 from Kalshi API."""


class KalshiClockSkewError(Exception):
    """Raised when local clock differs from server by more than MAX_CLOCK_SKEW_MS."""


class KalshiHTTPError(Exception):
    """Raised on non-2xx HTTP responses."""

    def __init__(self, status: int, code: str, msg: str) -> None:
        super().__init__(f"HTTP {status}: [{code}] {msg}")
        self.status = status
        self.code = code
        self.msg = msg


def _redact_processor(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor: redact sensitive headers/values."""
    sensitive_keys = {"authorization", "private_key", "pem", "secret"}
    for key in list(event_dict.keys()):
        lower = key.lower()
        if lower.startswith("kalshi-access-") or any(s in lower for s in sensitive_keys):
            event_dict[key] = "[REDACTED]"
    return event_dict


def _configure_logging(log_format: str) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_processor,
    ]
    if log_format == "console":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(processors=processors)


class _KalshiAuth(httpx.Auth):
    """httpx Auth plugin that signs every request with RSA-PSS."""

    def __init__(self, settings: Settings) -> None:
        assert settings.kalshi_api_key_id is not None, "kalshi_api_key_id must be set"
        assert settings.kalshi_private_key_path is not None, "kalshi_private_key_path must be set"
        self._key_id = settings.kalshi_api_key_id
        self._private_key = load_private_key(settings.kalshi_private_key_path)

    def auth_flow(
        self, request: httpx.Request
    ) -> Any:
        headers = build_headers(
            key_id=self._key_id,
            private_key=self._private_key,
            method=request.method,
            path_or_url=str(request.url),
        )
        for k, v in headers.items():
            request.headers[k] = v
        yield request


class _TokenBucket:
    """Minimal sync token-bucket rate limiter."""

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()

    def consume(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
        self._last = now
        if self._tokens < 1:
            sleep_for = (1 - self._tokens) / self._rate
            time.sleep(sleep_for)
            self._tokens = 0
        else:
            self._tokens -= 1


class KalshiClient:
    """Phase 0 Kalshi REST client. Authenticated, rate-limited, structlog-instrumented."""

    def __init__(self, settings: Settings) -> None:
        _configure_logging(settings.LOG_FORMAT)
        self._settings = settings
        self._base_url = settings.kalshi_rest_base_url
        self._auth = _KalshiAuth(settings)
        self._bucket = _TokenBucket(rate=CLIENT_READ_RPS)
        self._http = httpx.Client(
            base_url=self._base_url,
            auth=self._auth,
            timeout=10.0,
        )
        self._clock_checked = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method.upper() == "GET":
            self._bucket.consume()
        start = time.monotonic()
        response = self._http.request(method, path, **kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "kalshi_api_call",
            method=method.upper(),
            path=path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        if response.status_code in (401, 403):
            raise KalshiAuthError(f"Auth failed: {response.status_code} {response.text}")
        if not response.is_success:
            try:
                body = response.json()
                code = body.get("code", "unknown")
                msg = body.get("message", response.text)
            except Exception:
                code, msg = "parse_error", response.text
            raise KalshiHTTPError(response.status_code, code, msg)
        return response.json()  # type: ignore[no-any-return]

    def _check_clock_skew(self) -> None:
        """Fetch /exchange/status and compare Date header to local time."""
        if self._clock_checked:
            return
        response = self._http.get("/exchange/status")
        date_header = response.headers.get("Date", "")
        if date_header:
            server_dt = parsedate_to_datetime(date_header)
            server_ms = int(server_dt.timestamp() * 1000)
            local_ms = int(time.time() * 1000)
            skew = abs(local_ms - server_ms)
            if skew > MAX_CLOCK_SKEW_MS:
                raise KalshiClockSkewError(
                    f"Clock skew {skew}ms exceeds limit {MAX_CLOCK_SKEW_MS}ms"
                )
        self._clock_checked = True

    # ------------------------------------------------------------------
    # Phase 0 — read-only market/account endpoints
    # ------------------------------------------------------------------

    def get_exchange_status(self) -> dict[str, Any]:
        self._check_clock_skew()
        return self._request("GET", "/exchange/status")

    def get_balance(self) -> dict[str, Any]:
        self._check_clock_skew()
        return self._request("GET", "/portfolio/balance")

    def get_markets(
        self,
        *,
        status: str = "open",
        limit: int = 1000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._check_clock_skew()
        params: dict[str, Any] = {"status": status, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._request("GET", "/markets", params=params)

    def get_market(self, ticker: str) -> dict[str, Any]:
        self._check_clock_skew()
        return self._request("GET", f"/markets/{ticker}")

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict[str, Any]:
        self._check_clock_skew()
        return self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})

    # ------------------------------------------------------------------
    # Phase 4 — portfolio/order endpoints
    # ------------------------------------------------------------------

    def place_order(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /portfolio/orders — caller supplies the fully-formed body
        including client_order_id, count_fp and yes_price_dollars."""
        self._check_clock_skew()
        return self._request("POST", "/portfolio/orders", json=body)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """DELETE /portfolio/orders/{order_id}."""
        self._check_clock_skew()
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def cancel_all(self) -> dict[str, Any]:
        """DELETE /portfolio/orders — cancels every open order."""
        self._check_clock_skew()
        return self._request("DELETE", "/portfolio/orders")

    def get_positions(self) -> dict[str, Any]:
        """GET /portfolio/positions."""
        self._check_clock_skew()
        return self._request("GET", "/portfolio/positions")

    def get_orders(self, **kwargs: Any) -> dict[str, Any]:
        """GET /portfolio/orders — accepts query params (client_order_id, status, etc.)."""
        self._check_clock_skew()
        params = {k: v for k, v in kwargs.items() if v is not None}
        return self._request("GET", "/portfolio/orders", params=params)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> KalshiClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
