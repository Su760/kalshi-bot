"""Phase 4 integration stub — real demo-API round-trip.

Skipped by default. Enable with:  pytest tests/integration -m integration
Phase 6 (reconciliation) will flesh this out with a full place → poll → cancel loop.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Phase 4 stub — implemented in Phase 6 reconciliation")
def test_place_and_cancel_roundtrip() -> None:
    """TODO (Phase 6): place a tiny far-from-mid post-only limit, verify resting,
    cancel, verify canceled. Must use demo API and a throwaway ticker."""
    raise NotImplementedError
