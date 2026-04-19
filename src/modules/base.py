"""SignalModule protocol and Signal dataclass — the frozen interface all modules implement."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from src.core.types import Market


@dataclass(frozen=True)
class Signal:
    my_probability: float        # [0, 1] — my estimate of YES settling
    confidence: float            # [0, 1] — how much to trust this estimate
    data_freshness_seconds: int  # age of underlying data
    source_module: str           # module name e.g. "scanner", "weather"
    debug: dict[str, object] = field(default_factory=dict)  # free-form, logged with signal

    def __post_init__(self) -> None:
        if not 0.0 <= self.my_probability <= 1.0:
            raise ValueError(f"my_probability must be in [0,1], got {self.my_probability}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if self.data_freshness_seconds < 0:
            raise ValueError("data_freshness_seconds must be >= 0")


@runtime_checkable
class SignalModule(Protocol):
    name: str
    enabled: bool

    def applies_to(self, market: Market) -> bool:
        """Return True if this module has an opinion about this market."""
        ...

    def predict(self, market: Market, now: datetime) -> Signal | None:
        """
        Return a probability estimate for YES settling, or None if no opinion.
        MUST be idempotent and side-effect-free beyond internal caching.
        """
        ...
