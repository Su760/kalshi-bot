"""Stub RiskManager for Phase 4. Phase 5 replaces this with real risk checks."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.execution import OrderIntent


class KillSwitchActive(Exception):
    """Raised when kill switch is set. Never catch this inside the executor."""


class RiskError(Exception):
    """Raised when a risk limit is exceeded."""


class RiskManagerStub:
    """Phase 4 stub — always allows orders. Phase 5 replaces with real implementation."""

    def check(self, intent: OrderIntent) -> None:
        """No-op for Phase 4. Phase 5 adds real checks here."""
        return None
