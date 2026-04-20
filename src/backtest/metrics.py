"""Pure metric functions for backtest evaluation."""
from __future__ import annotations

import math
import statistics
from typing import Any


def brier_score(probs: list[float], outcomes: list[int]) -> float:
    """mean((p - y)^2). Lower is better."""
    if not probs:
        return 0.0
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes, strict=False)) / len(probs)


def brier_skill_score(probs: list[float], outcomes: list[int]) -> float:
    """BSS = 1 - BS/BS_climatology. Positive = better than climatology."""
    if not outcomes:
        return 0.0
    clim = sum(outcomes) / len(outcomes)
    bs_clim = brier_score([clim] * len(outcomes), outcomes)
    if bs_clim == 0.0:
        return 0.0
    return 1.0 - brier_score(probs, outcomes) / bs_clim


def log_loss(probs: list[float], outcomes: list[int]) -> float:
    """mean(-y*log(p) - (1-y)*log(1-p)). Clips probs to [1e-7, 1-1e-7]."""
    if not probs:
        return 0.0
    eps = 1e-7
    total = 0.0
    for p, y in zip(probs, outcomes, strict=False):
        p = max(eps, min(1 - eps, p))
        total += -y * math.log(p) - (1 - y) * math.log(1 - p)
    return total / len(probs)


def pnl_z_score(
    realized_pnl: float,
    bets: list[tuple[float, float, float]],
) -> float:
    """
    Z-score of realized P&L vs expected.
    bets: list of (contracts, cost_per_contract, my_probability)
    Z = (realized - expected) / sqrt(sum(variance_i))
    variance_i = contracts_i^2 * cost_i * (1 - cost_i)
    """
    if not bets:
        return 0.0
    expected = sum(c * (p - cost) for c, cost, p in bets)
    variance = sum(c**2 * cost * (1 - cost) for c, cost, p in bets)
    if variance <= 0.0:
        return 0.0
    return (realized_pnl - expected) / math.sqrt(variance)


def sharpe_ratio(daily_pnl: list[float], annualize: bool = True) -> float:
    """
    Sharpe = mean(daily_pnl) / std(daily_pnl).
    Annualized by * sqrt(252) if annualize=True.
    Returns 0.0 if std is 0 or fewer than 2 observations.
    """
    if len(daily_pnl) < 2:
        return 0.0
    mean = statistics.mean(daily_pnl)
    std = statistics.stdev(daily_pnl)
    if std == 0.0:
        return 0.0
    ratio = mean / std
    return ratio * math.sqrt(252) if annualize else ratio


def max_drawdown(equity_curve: list[float]) -> float:
    """
    Maximum peak-to-trough decline as a fraction.
    Returns value in [0, 1]. 0.0 if fewer than 2 points.
    """
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        if peak > 0:
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def calibration_buckets(
    probs: list[float],
    outcomes: list[int],
    n_buckets: int = 10,
) -> list[dict[str, Any]]:
    """
    Bucket predictions into n_buckets bins.
    Returns list of dicts: bucket_low, bucket_high, mean_prob, empirical_freq, count.
    Only includes buckets with count > 0.
    """
    if not probs:
        return []
    width = 1.0 / n_buckets
    buckets: dict[int, list[tuple[float, int]]] = {}
    for p, y in zip(probs, outcomes, strict=False):
        idx = min(int(p / width), n_buckets - 1)
        buckets.setdefault(idx, []).append((p, y))

    result = []
    for idx in sorted(buckets):
        items = buckets[idx]
        ps = [x[0] for x in items]
        ys = [x[1] for x in items]
        result.append(
            {
                "bucket_low": idx * width,
                "bucket_high": (idx + 1) * width,
                "mean_prob": sum(ps) / len(ps),
                "empirical_freq": sum(ys) / len(ys),
                "count": len(items),
            }
        )
    return result
