"""Dead-man heartbeat — pings the heartbeats table every 5 seconds.

If no ping arrives for HEARTBEAT_TIMEOUT_S seconds, Tier 6 of the
risk layer trips the kill switch.
"""
from __future__ import annotations

import sqlite3
import threading
import time

import structlog

from src.storage.db import get_db

logger = structlog.get_logger(__name__)


class HeartbeatThread:
    """Background thread that writes to heartbeats table every 5s."""

    PING_INTERVAL_S = 5

    def __init__(self, db_path: str) -> None:
        self._db = get_db(db_path)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        self._db.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                now_ms = int(time.time() * 1000)
                self._db.execute(
                    """INSERT INTO heartbeats (thread_name, ts_ms) VALUES ('main', ?)
                       ON CONFLICT(thread_name) DO UPDATE SET ts_ms = excluded.ts_ms""",
                    (now_ms,),
                )
                self._db.commit()
            except sqlite3.OperationalError as exc:
                logger.debug("heartbeat_ping_skipped", reason=str(exc))
            except Exception:
                logger.exception("heartbeat_ping_failed")
            self._stop.wait(self.PING_INTERVAL_S)
