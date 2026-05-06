"""KalshiWebSocket — real-time orderbook + trade collector.

One `KalshiWebSocket` owns:

* a dedicated daemon thread running `asyncio.run(...)` — the event loop
  lives entirely inside that thread;
* a `LocalOrderbook` per subscribed ticker, fed by WS snapshot/delta
  messages on the event loop;
* a batch writer task that drains rows into SQLite every 500ms or every
  100 rows, whichever is first;
* a reconnect loop with jittered exponential backoff capped at 60s.

Callbacks registered via `on_orderbook_update` / `on_trade` are invoked
on the event loop thread and MUST be cheap. Slow consumers belong on a
separate executor.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import random
import sqlite3
import threading
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import structlog
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from websockets.asyncio.client import ClientConnection, connect

from src.config.settings import Settings
from src.core.auth import build_headers, load_private_key
from src.core.client import KalshiClient
from src.core.orderbook import LocalOrderbook
from src.core.types import Orderbook, Trade
from src.observability.metrics import ws_messages_total, ws_reconnects_total
from src.storage.db import get_db
from src.storage.orderbook_writer import (
    insert_orderbook_snapshots,
    insert_trade,
)

logger = structlog.get_logger(__name__)

_SUBSCRIBE_BATCH_SIZE = 500
_BATCH_FLUSH_ROWS = 100
_BATCH_FLUSH_INTERVAL_S = 0.5
_BACKOFF_INITIAL_S = 1.0
_BACKOFF_CAP_S = 60.0

OrderbookCallback = Callable[[str, Orderbook], None]
TradeCallback = Callable[[Trade], None]


def _rest_to_snapshot_msg(ticker: str, resp: dict[str, Any]) -> dict[str, Any]:
    """Adapt the REST /markets/{ticker}/orderbook response to the shape
    that `LocalOrderbook.apply_snapshot` expects.

    REST returns prices in integer CENTS and sizes in `count`. WS uses
    dollar-decimal strings. We convert on the way in so the book always
    stores Decimal dollar prices.
    """
    ob = resp.get("orderbook", resp)
    yes_raw = ob.get("yes") or []
    no_raw = ob.get("no") or []

    def _convert(rows: list[list[int]]) -> list[list[Any]]:
        converted: list[list[Any]] = []
        for row in rows:
            price_cents = int(row[0])
            size = int(row[1])
            price_dollars = str(Decimal(price_cents) / Decimal(100))
            converted.append([price_dollars, size])
        return converted

    return {
        "type": "orderbook_snapshot",
        "msg": {
            "market_ticker": ticker,
            # Use a synthetic seq marker. Deltas will be gated on the next
            # live WS seq anyway — this just seeds the counter.
            "seq": 0,
            "yes": _convert(yes_raw),
            "no": _convert(no_raw),
        },
    }


def _persistence_row(book: LocalOrderbook, ob: Orderbook) -> dict[str, Any]:
    """Build the dict payload for orderbook_writer.insert_orderbook_snapshots."""
    best_yes = book.best_yes_bid()
    best_no = book.best_no_bid()
    yes_ask = book.yes_ask_impl()
    no_ask = Decimal("1") - best_yes if best_yes is not None else None
    mid_yes = book.mid_yes()
    spread = book.spread_cents()
    return {
        "ticker": ob.ticker,
        "ts_ms": ob.ts_ms,
        "seq": ob.seq,
        "yes_bids_json": json.dumps(
            [[str(lvl.price), lvl.size] for lvl in ob.yes_bids]
        ),
        "no_bids_json": json.dumps(
            [[str(lvl.price), lvl.size] for lvl in ob.no_bids]
        ),
        "best_yes_bid": str(best_yes) if best_yes is not None else None,
        "best_no_bid": str(best_no) if best_no is not None else None,
        "yes_ask_impl": str(yes_ask) if yes_ask is not None else None,
        "no_ask_impl": str(no_ask) if no_ask is not None else None,
        "mid_yes": str(mid_yes) if mid_yes is not None else None,
        "spread_cents": spread,
        "source": "ws",
    }


class KalshiWebSocket:
    """Kalshi market-data WebSocket client.

    Typical lifecycle:

        ws = KalshiWebSocket(settings, client, tickers=["KXNFL-SB-KC"])
        ws.on_orderbook_update(lambda t, ob: ...)
        ws.on_trade(lambda tr: ...)
        ws.start()
        ...
        ws.stop()
    """

    def __init__(
        self,
        settings: Settings,
        client: KalshiClient,
        tickers: list[str],
    ) -> None:
        self._settings = settings
        self._client = client
        self._tickers: list[str] = list(tickers)
        assert settings.kalshi_private_key_path is not None, "kalshi_private_key_path must be set"
        self._private_key: RSAPrivateKey = load_private_key(
            settings.kalshi_private_key_path
        )
        self._books: dict[str, LocalOrderbook] = {
            t: LocalOrderbook(t) for t in self._tickers
        }
        self._orderbook_callbacks: list[OrderbookCallback] = []
        self._trade_callbacks: list[TradeCallback] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cmd_id = 0
        self._reconnects_total = 0
        self._conn: sqlite3.Connection | None = None
        self._write_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._resync_inflight: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_orderbook_update(self, cb: OrderbookCallback) -> None:
        self._orderbook_callbacks.append(cb)

    def on_trade(self, cb: TradeCallback) -> None:
        self._trade_callbacks.append(cb)

    def get_orderbook(self, ticker: str) -> LocalOrderbook | None:
        """Thread-safe accessor for Phase 3 scanner threads."""
        return self._books.get(ticker)

    @property
    def reconnects_total(self) -> int:
        return self._reconnects_total

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("KalshiWebSocket already started")
        self._thread = threading.Thread(
            target=self._thread_main,
            name="kalshi-ws",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    # ------------------------------------------------------------------
    # Thread / event-loop plumbing
    # ------------------------------------------------------------------

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._async_main())
        except Exception:
            logger.exception("ws_thread_crashed")

    async def _async_main(self) -> None:
        self._conn = get_db(self._settings.DB_PATH)
        self._write_queue = asyncio.Queue()
        writer_task = asyncio.create_task(self._batch_writer())
        try:
            await self._connect_loop()
        finally:
            writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await writer_task
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------
    # Connect / reconnect loop
    # ------------------------------------------------------------------

    async def _connect_loop(self) -> None:
        backoff = _BACKOFF_INITIAL_S
        while not self._stop_event.is_set():
            try:
                await self._connect_and_run()
                backoff = _BACKOFF_INITIAL_S  # clean exit → reset backoff
            except Exception as exc:
                self._reconnects_total += 1
                ws_reconnects_total.inc()
                jitter = random.uniform(0, backoff * 0.25)
                delay = min(backoff + jitter, _BACKOFF_CAP_S)
                logger.warning(
                    "ws_reconnect",
                    error=str(exc),
                    backoff_s=round(delay, 2),
                    reconnects_total=self._reconnects_total,
                )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.to_thread(self._stop_event.wait, delay),
                        timeout=delay + 1,
                    )
                backoff = min(backoff * 2, _BACKOFF_CAP_S)

    async def _connect_and_run(self) -> None:
        assert self._settings.kalshi_api_key_id is not None, "kalshi_api_key_id must be set"
        headers = build_headers(
            key_id=self._settings.kalshi_api_key_id,
            private_key=self._private_key,
            method="GET",
            path_or_url=self._settings.kalshi_ws_url,
        )
        async with connect(
            self._settings.kalshi_ws_url,
            additional_headers=headers,
            ping_interval=15,
            ping_timeout=10,
            max_size=2**22,
        ) as ws:
            logger.info("ws_connected", tickers=len(self._tickers))
            await self._subscribe_all(ws)
            async for raw in ws:
                if self._stop_event.is_set():
                    break
                await self._handle_message(raw)

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def _next_cmd_id(self) -> int:
        self._cmd_id += 1
        return self._cmd_id

    async def _subscribe_all(self, ws: ClientConnection) -> None:
        """Send subscribe frames in batches of ≤500 tickers per message.

        Kalshi sends an `orderbook_snapshot` automatically on initial
        `orderbook_delta` subscription; subsequent messages are deltas.
        """
        for i in range(0, len(self._tickers), _SUBSCRIBE_BATCH_SIZE):
            batch = self._tickers[i : i + _SUBSCRIBE_BATCH_SIZE]
            for channel in ("trade", "orderbook_delta"):
                payload = {
                    "id": self._next_cmd_id(),
                    "cmd": "subscribe",
                    "params": {
                        "channels": [channel],
                        "market_tickers": batch,
                    },
                }
                await ws.send(json.dumps(payload))

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    async def _handle_message(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ws_decode_failed", raw=str(raw)[:200])
            return
        mtype = msg.get("type")
        _label = (
            "snapshot" if mtype == "orderbook_snapshot"
            else "delta" if mtype == "orderbook_delta"
            else "trade" if mtype == "trade"
            else "subscribed" if mtype in ("subscribed", "ok")
            else "error" if mtype == "error"
            else "unknown"
        )
        ws_messages_total.labels(type=_label).inc()
        try:
            if mtype == "orderbook_snapshot":
                await self._on_snapshot(msg)
            elif mtype == "orderbook_delta":
                await self._on_delta(msg)
            elif mtype == "trade":
                await self._on_trade(msg)
            elif mtype in ("subscribed", "ok"):
                logger.info("ws_ctrl", type=mtype)
            elif mtype == "error":
                logger.warning("ws_error", msg=msg)
            else:
                logger.debug("ws_unhandled", type=mtype)
        except Exception:
            logger.exception("ws_handle_message_error", mtype=mtype)

    def _ticker_of(self, msg: dict[str, Any]) -> str | None:
        m = msg.get("msg", {})
        t = m.get("market_ticker") or m.get("ticker")
        return t if isinstance(t, str) else None

    async def _on_snapshot(self, msg: dict[str, Any]) -> None:
        ticker = self._ticker_of(msg)
        if ticker is None:
            return
        book = self._books.get(ticker)
        if book is None:
            return
        book.apply_snapshot(msg)
        if self._write_queue is not None:
            ob = book.to_orderbook()
            await self._write_queue.put(_persistence_row(book, ob))

    async def _on_delta(self, msg: dict[str, Any]) -> None:
        ticker = self._ticker_of(msg)
        if ticker is None:
            return
        book = self._books.get(ticker)
        if book is None:
            return
        ob = book.apply_delta(msg)
        if ob is None:
            self._schedule_resync(ticker)
            return
        assert self._write_queue is not None
        await self._write_queue.put(_persistence_row(book, ob))
        for cb in self._orderbook_callbacks:
            try:
                cb(ticker, ob)
            except Exception:
                logger.exception("orderbook_cb_failed", ticker=ticker)

    async def _on_trade(self, msg: dict[str, Any]) -> None:
        m = msg.get("msg", {})
        try:
            trade = Trade(
                trade_id=str(m["trade_id"]),
                ticker=str(m.get("market_ticker") or m.get("ticker") or ""),
                ts_ms=int(m.get("ts") or m.get("created_time") or int(time.time() * 1000)),
                side=str(m.get("taker_side") or m.get("side") or "yes"),
                action=str(m.get("action") or "buy"),
                yes_price=str(m.get("yes_price_dollars") or m.get("yes_price") or "0"),
                count=int(m.get("count_fp") or m.get("count") or 0),
                is_our_fill=False,
            )
        except (KeyError, ValueError, TypeError):
            logger.warning("trade_parse_failed", msg=m)
            return
        for cb in self._trade_callbacks:
            try:
                cb(trade)
            except Exception:
                logger.exception("trade_cb_failed", trade_id=trade.trade_id)
        if self._conn is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, insert_trade, self._conn, trade)

    # ------------------------------------------------------------------
    # Seq-gap resync
    # ------------------------------------------------------------------

    def _schedule_resync(self, ticker: str) -> None:
        if ticker in self._resync_inflight:
            return
        self._resync_inflight.add(ticker)
        logger.warning("ws_seq_gap_resync", ticker=ticker)
        asyncio.create_task(self._resync_ticker(ticker))

    async def _resync_ticker(self, ticker: str) -> None:
        try:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                None, self._client.get_orderbook, ticker, 100
            )
            snapshot_msg = _rest_to_snapshot_msg(ticker, resp)
            book = self._books.get(ticker)
            if book is not None:
                book.apply_snapshot(snapshot_msg)
                if self._write_queue is not None:
                    ob = book.to_orderbook()
                    await self._write_queue.put(_persistence_row(book, ob))
            logger.info("ws_resync_ok", ticker=ticker)
        except Exception:
            logger.exception("ws_resync_failed", ticker=ticker)
        finally:
            self._resync_inflight.discard(ticker)

    # ------------------------------------------------------------------
    # Batch writer
    # ------------------------------------------------------------------

    async def _batch_writer(self) -> None:
        """Drain `_write_queue` into SQLite.

        Flushes when the buffer reaches `_BATCH_FLUSH_ROWS` rows OR when
        `_BATCH_FLUSH_INTERVAL_S` seconds have elapsed since the last flush
        and at least one row is queued.
        """
        assert self._write_queue is not None
        buffer: list[dict[str, Any]] = []
        last_flush = time.monotonic()
        while not self._stop_event.is_set():
            try:
                row = await asyncio.wait_for(
                    self._write_queue.get(), timeout=0.1
                )
                buffer.append(row)
            except TimeoutError:
                pass
            elapsed = time.monotonic() - last_flush
            if len(buffer) >= _BATCH_FLUSH_ROWS or (
                buffer and elapsed >= _BATCH_FLUSH_INTERVAL_S
            ):
                await self._flush(buffer)
                buffer.clear()
                last_flush = time.monotonic()
        if buffer:
            await self._flush(buffer)

    async def _flush(self, rows: list[dict[str, Any]]) -> None:
        if self._conn is None or not rows:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, insert_orderbook_snapshots, self._conn, rows
            )
        except Exception:
            logger.exception("batch_flush_failed", rows=len(rows))
