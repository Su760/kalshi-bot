"""Known-answer tests for backtest metric functions."""
from __future__ import annotations

import pytest

from src.backtest.metrics import (
    brier_score,
    brier_skill_score,
    calibration_buckets,
    log_loss,
    max_drawdown,
    pnl_z_score,
    sharpe_ratio,
)


def test_brier_score_perfect_predictor() -> None:
    assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == pytest.approx(0.0)


def test_brier_score_worst_predictor() -> None:
    assert brier_score([0.0, 1.0], [1, 0]) == pytest.approx(1.0)


def test_brier_score_climatology() -> None:
    assert brier_score([0.5, 0.5], [1, 0]) == pytest.approx(0.25)


def test_bss_positive_for_good_model() -> None:
    probs = [0.9, 0.1, 0.8, 0.2]
    outcomes = [1, 0, 1, 0]
    assert brier_skill_score(probs, outcomes) > 0


def test_bss_zero_for_climatology() -> None:
    outcomes = [1, 0, 1, 0]
    probs = [0.5, 0.5, 0.5, 0.5]
    assert brier_skill_score(probs, outcomes) == pytest.approx(0.0, abs=1e-6)


def test_max_drawdown_flat() -> None:
    assert max_drawdown([100.0, 100.0, 100.0]) == pytest.approx(0.0)


def test_max_drawdown_monotone_decline() -> None:
    assert max_drawdown([1000.0, 800.0, 600.0]) == pytest.approx(0.4)


def test_max_drawdown_recovery() -> None:
    assert max_drawdown([1000.0, 900.0, 1100.0, 800.0]) == pytest.approx(
        (1100 - 800) / 1100, rel=1e-4
    )


def test_sharpe_all_positive() -> None:
    daily = [0.01, 0.02, 0.015, 0.01]
    assert sharpe_ratio(daily, annualize=False) > 0


def test_sharpe_returns_zero_for_single_observation() -> None:
    assert sharpe_ratio([0.01], annualize=False) == pytest.approx(0.0)


def test_pnl_z_score_positive_for_edge() -> None:
    bets = [(10, 0.40, 0.60), (10, 0.40, 0.60)]
    realized = 10 * (1 - 0.40) + 10 * (1 - 0.40)
    assert pnl_z_score(realized, bets) > 0


def test_pnl_z_score_zero_variance() -> None:
    assert pnl_z_score(0.0, []) == pytest.approx(0.0)
