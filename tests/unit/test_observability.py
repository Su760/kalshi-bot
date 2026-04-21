"""Unit tests for Prometheus metrics instrumentation."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_ws_reconnects_counter_increments() -> None:
    """ws_reconnects_total increments correctly."""
    from src.observability.metrics import ws_reconnects_total
    before = ws_reconnects_total._value.get()
    ws_reconnects_total.inc()
    assert ws_reconnects_total._value.get() == before + 1.0


def test_ws_messages_counter_with_label() -> None:
    """ws_messages_total increments with correct label."""
    from src.observability.metrics import ws_messages_total
    before = ws_messages_total.labels(type="snapshot")._value.get()
    ws_messages_total.labels(type="snapshot").inc()
    assert ws_messages_total.labels(type="snapshot")._value.get() == before + 1.0


def test_orders_submitted_paper_mode() -> None:
    from src.observability.metrics import orders_submitted_total
    before = orders_submitted_total.labels(mode="paper")._value.get()
    orders_submitted_total.labels(mode="paper").inc()
    assert orders_submitted_total.labels(mode="paper")._value.get() == before + 1.0


def test_kill_switch_trips_with_reason() -> None:
    from src.observability.metrics import kill_switch_trips_total
    before = kill_switch_trips_total.labels(reason="drawdown")._value.get()
    kill_switch_trips_total.labels(reason="drawdown").inc()
    assert kill_switch_trips_total.labels(reason="drawdown")._value.get() == before + 1.0


def test_balance_gauge_set() -> None:
    from src.observability.metrics import balance_dollars
    balance_dollars.set(123.45)
    assert balance_dollars._value.get() == pytest.approx(123.45)


def test_metrics_exporter_disabled_does_not_start() -> None:
    from src.observability.exporter import MetricsExporter
    exporter = MetricsExporter(port=9999, enabled=False)
    exporter.start()
    assert not exporter.started


def test_metrics_exporter_enabled_starts() -> None:
    from src.observability.exporter import MetricsExporter
    with patch("src.observability.exporter.start_http_server") as mock_start:
        exporter = MetricsExporter(port=9876, enabled=True)
        exporter.start()
        mock_start.assert_called_once_with(9876)
        assert exporter.started


def test_metrics_exporter_idempotent() -> None:
    """Calling start() twice should only start the server once."""
    from src.observability.exporter import MetricsExporter
    with patch("src.observability.exporter.start_http_server") as mock_start:
        exporter = MetricsExporter(port=9875, enabled=True)
        exporter.start()
        exporter.start()
        assert mock_start.call_count == 1
