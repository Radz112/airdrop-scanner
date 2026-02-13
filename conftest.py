from __future__ import annotations

import pytest

from app.models.response import TokenedSignal, TokenlessSignal


@pytest.fixture
def make_tokenless_signal():
    """Factory fixture for creating TokenlessSignal instances."""

    def _make(
        protocol_id: str = "test_proto",
        protocol_name: str = "Test Protocol",
        category: str = "dex",
        protocol_weight: float = 1.0,
        interacted: bool = False,
        first_seen: str | None = None,
        last_seen: str | None = None,
        interaction_count: int = 0,
        signal_types: list[str] | None = None,
        signal_strength: str = "none",
        detection_mode: str = "event_topic",
    ) -> TokenlessSignal:
        return TokenlessSignal(
            protocol_id=protocol_id,
            protocol_name=protocol_name,
            category=category,
            protocol_weight=protocol_weight,
            interacted=interacted,
            first_seen=first_seen,
            last_seen=last_seen,
            interaction_count=interaction_count,
            signal_types=signal_types or [],
            signal_strength=signal_strength,
            detection_mode=detection_mode,
        )

    return _make


@pytest.fixture
def make_tokened_signal():
    """Factory fixture for creating TokenedSignal instances."""

    def _make(
        protocol_id: str = "test_tokened",
        protocol_name: str = "Tokened Protocol",
        category: str = "dex",
        token_symbol: str = "TKN",
        interacted: bool = False,
        note: str = "",
    ) -> TokenedSignal:
        return TokenedSignal(
            protocol_id=protocol_id,
            protocol_name=protocol_name,
            category=category,
            token_symbol=token_symbol,
            interacted=interacted,
            note=note,
        )

    return _make
