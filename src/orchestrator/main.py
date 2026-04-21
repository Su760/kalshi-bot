"""OrchestratorLoop — wires all components and runs the bot.

Startup sequence:
  1. Init DB + apply schema
  2. Start HeartbeatThread
  3. Start MetricsExporter
  4. Init REST client
  5. Fetch + seed universe
  6. Start KalshiWebSocket (subscribes to top N tickers by open_interest)
  7. Init RiskManager (fetches balance)
  8. Init Executor (paper mode)
  9. Wire executor into RiskManager (set_executor)
  10. Init Reconciler
  11. Init Scanner
  12. Init ScanLoop
  13. Enter main loop

Shutdown sequence (on SIGINT/SIGTERM/KillSwitchActive/any exception):
  1. Stop WS
  2. Stop HeartbeatThread
  3. Executor.cancel_all() if LIVE_TRADING
  4. Close client
  5. Close DB
"""
from __future__ import annotations

import signal
import sqlite3
import time
from typing import Any

import structlog

from src.config.settings import Settings
from src.core.client import KalshiClient
from src.core.execution import Executor
from src.core.reconcile import Reconciler
from src.core.risk import RiskManager
from src.core.risk_stub import KillSwitchActive
from src.core.scanner import Scanner
from src.core.types import Market
from src.core.universe import UniverseFetcher
from src.core.ws import KalshiWebSocket
from src.observability.exporter import MetricsExporter
from src.orchestrator.heartbeat import HeartbeatThread
from src.orchestrator.loop import ScanLoop
from src.storage.db import apply_schema, get_default_db

logger = structlog.get_logger(__name__)

SCHEMA_PATH = "src/storage/schema.sql"
UNIVERSE_REFRESH_INTERVAL_S = 1800
MAX_WS_TICKERS = 200
SCAN_INTERVAL_S = 5.0
TICK_SLEEP_S = 0.1


class OrchestratorLoop:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._running = False
        self._db: sqlite3.Connection | None = None
        self._client: KalshiClient | None = None
        self._ws: KalshiWebSocket | None = None
        self._heartbeat: HeartbeatThread | None = None
        self._exporter: MetricsExporter | None = None
        self._risk: RiskManager | None = None
        self._executor: Executor | None = None
        self._reconciler: Reconciler | None = None
        self._scanner: Scanner | None = None
        self._fetcher: UniverseFetcher | None = None
        self._scan_loop: ScanLoop | None = None
        self._last_universe_refresh_ms: int = 0
        self._last_reconcile_ms: int = 0

    def start(self) -> None:
        """Initialize all components and enter the main loop."""
        logger.info("orchestrator_starting")
        self._setup()
        self._register_signals()
        self._running = True
        logger.info(
            "orchestrator_running",
            live=self._settings.LIVE_TRADING,
            paper=not self._settings.LIVE_TRADING,
        )
        try:
            self._run_loop()
        except KeyboardInterrupt:
            logger.info("orchestrator_keyboard_interrupt")
        finally:
            self._shutdown()

    def stop(self) -> None:
        """Signal the main loop to stop cleanly."""
        self._running = False

    def _setup(self) -> None:
        """Initialize every component in dependency order."""
        self._db = get_default_db()
        apply_schema(self._db, SCHEMA_PATH)

        self._heartbeat = HeartbeatThread(self._db)
        self._heartbeat.start()

        self._exporter = MetricsExporter(
            port=self._settings.PROMETHEUS_PORT,
            enabled=self._settings.PROMETHEUS_ENABLED,
        )
        self._exporter.start()

        self._client = KalshiClient(self._settings)

        self._fetcher = UniverseFetcher(self._client)
        self._refresh_universe()

        tickers = self._get_top_tickers(MAX_WS_TICKERS)
        logger.info("ws_subscribing", count=len(tickers))
        self._ws = KalshiWebSocket(self._settings, self._client, tickers=tickers)
        self._ws.start()

        self._risk = RiskManager(
            client=self._client,
            settings=self._settings,
            db_conn=self._db,
        )

        self._executor = Executor(
            client=self._client,
            settings=self._settings,
            risk=self._risk,
            db_conn=self._db,
        )
        self._risk.set_executor(self._executor)

        self._reconciler = Reconciler(
            client=self._client,
            settings=self._settings,
            db_conn=self._db,
            risk=self._risk,
        )

        self._scanner = Scanner(
            live_books=self._ws._books,
            markets_by_event=self._build_markets_by_event(),
        )

        self._scan_loop = ScanLoop(
            scanner=self._scanner,
            executor=self._executor,
            db_conn=self._db,
            settings=self._settings,
        )

    def _run_loop(self) -> None:
        """Main loop — runs until self._running is False."""
        assert self._scan_loop is not None

        last_scan_ms = 0

        while self._running:
            now_ms = int(time.time() * 1000)

            try:
                if (
                    now_ms - self._last_universe_refresh_ms
                    > UNIVERSE_REFRESH_INTERVAL_S * 1000
                ):
                    self._refresh_universe()

                if (
                    now_ms - self._last_reconcile_ms
                    > self._settings.RECONCILE_INTERVAL_S * 1000
                ):
                    self._run_reconcile()

                if now_ms - last_scan_ms > SCAN_INTERVAL_S * 1000:
                    self._scan_loop.run_once()
                    last_scan_ms = now_ms

            except KillSwitchActive as exc:
                logger.error("orchestrator_kill_switch", reason=str(exc))
                self._running = False
                break
            except Exception:
                logger.exception("orchestrator_loop_error")

            time.sleep(TICK_SLEEP_S)

    def _shutdown(self) -> None:
        logger.info("orchestrator_shutting_down")
        if self._ws is not None:
            try:
                self._ws.stop()
            except Exception:
                logger.exception("orchestrator_ws_stop_failed")
        if self._heartbeat is not None:
            try:
                self._heartbeat.stop()
            except Exception:
                logger.exception("orchestrator_heartbeat_stop_failed")
        if self._executor is not None and self._settings.LIVE_TRADING:
            try:
                self._executor.cancel_all()
            except Exception:
                logger.exception("orchestrator_cancel_all_failed")
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.exception("orchestrator_client_close_failed")
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                logger.exception("orchestrator_db_close_failed")
        logger.info("orchestrator_stopped")

    def _refresh_universe(self) -> None:
        assert self._fetcher is not None
        assert self._db is not None
        try:
            markets = self._fetcher.fetch_all()
            count = self._fetcher.upsert(self._db, markets)
            logger.info("universe_refreshed", count=count)
            self._last_universe_refresh_ms = int(time.time() * 1000)
        except Exception:
            logger.exception("universe_refresh_failed")

    def _run_reconcile(self) -> None:
        assert self._reconciler is not None
        try:
            result = self._reconciler.reconcile_once()
            logger.info(
                "reconcile_complete",
                orphans=result.orphan_orders_canceled,
                lost=result.lost_orders_inserted,
                errors=len(result.errors),
            )
            self._last_reconcile_ms = int(time.time() * 1000)
        except Exception:
            logger.exception("reconcile_failed")

    def _get_top_tickers(self, n: int) -> list[str]:
        """Get top N tickers by open_interest from DB."""
        assert self._db is not None
        rows = self._db.execute(
            "SELECT ticker FROM markets WHERE status='open' "
            "ORDER BY open_interest DESC, volume_24h DESC LIMIT ?",
            (n,),
        ).fetchall()
        if not rows:
            rows = self._db.execute(
                "SELECT ticker FROM markets LIMIT ?", (n,)
            ).fetchall()
        return [r[0] for r in rows]

    def _build_markets_by_event(self) -> dict[str, list[Market]]:
        """Build event_ticker → [Market] mapping for bracket arb detection."""
        assert self._db is not None
        rows = self._db.execute(
            "SELECT * FROM markets WHERE status='open'"
        ).fetchall()
        result: dict[str, list[Market]] = {}
        for row in rows:
            try:
                market = Market(
                    ticker=row["ticker"],
                    event_ticker=row["event_ticker"],
                    series_ticker=row["series_ticker"],
                    category=row["category"],
                    title=row["title"],
                    subtitle=row["subtitle"],
                    status=row["status"],
                    strike_type=row["strike_type"],
                    floor_strike=row["floor_strike"],
                    cap_strike=row["cap_strike"],
                    tick_size=row["tick_size"],
                    price_level_structure=row["price_level_structure"],
                    open_time_ms=row["open_time_ms"],
                    close_time_ms=row["close_time_ms"] or 0,
                    latest_expiration_ms=row["latest_expiration_ms"],
                    settlement_source=row["settlement_source"],
                    volume_24h=row["volume_24h"] or 0,
                    open_interest=row["open_interest"] or 0,
                    last_price_cents=row["last_price_cents"],
                    raw_json=row["raw_json"],
                )
                result.setdefault(market.event_ticker, []).append(market)
            except Exception:
                continue
        return result

    def _register_signals(self) -> None:
        def handler(signum: int, frame: Any) -> None:
            logger.info("orchestrator_signal_received", signum=signum)
            self._running = False

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
