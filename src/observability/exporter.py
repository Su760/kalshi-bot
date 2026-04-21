"""HTTP metrics exporter — exposes /metrics on PROMETHEUS_PORT in a daemon thread."""
from __future__ import annotations

import structlog
from prometheus_client import start_http_server

logger = structlog.get_logger(__name__)


class MetricsExporter:
    def __init__(self, port: int = 8000, enabled: bool = True) -> None:
        self._port = port
        self._enabled = enabled
        self._started = False

    def start(self) -> None:
        if not self._enabled:
            logger.info("metrics_exporter_disabled")
            return
        if self._started:
            return
        start_http_server(self._port)
        self._started = True
        logger.info("metrics_exporter_started", port=self._port)

    @property
    def started(self) -> bool:
        return self._started
