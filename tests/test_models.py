from __future__ import annotations

from app.models.response import (
    DISCLAIMER,
    CategoryCoverage,
    NextAction,
    ScanResponse,
    SkippedProtocol,
    SummaryMetrics,
    TokenedSignal,
    TokenlessSignal,
)


class TestCategoryCoverage:
    def test_default_all_false(self):
        coverage = CategoryCoverage()
        dumped = coverage.model_dump(by_alias=True)
        assert all(v is False for v in dumped.values())
        assert len(dumped) == 10

    def test_yield_serializes_without_underscore(self):
        coverage = CategoryCoverage(yield_=True)
        dumped = coverage.model_dump(by_alias=True)
        assert "yield" in dumped
        assert "yield_" not in dumped
        assert dumped["yield"] is True

    def test_populate_by_name_works(self):
        """Can set yield_ using either the Python name or the alias."""
        c1 = CategoryCoverage(yield_=True)
        assert c1.yield_ is True
        c2 = CategoryCoverage(**{"yield": True})
        assert c2.yield_ is True

    def test_partial_coverage(self):
        coverage = CategoryCoverage(dex=True, bridge=True)
        assert coverage.dex is True
        assert coverage.bridge is True
        assert coverage.lending is False
        assert coverage.nft is False


class TestSummaryMetrics:
    def test_defaults(self):
        s = SummaryMetrics()
        assert s.tokenless_protocols_interacted == 0
        assert s.tokenless_protocols_available == 0
        assert s.total_protocols_scanned == 0
        assert s.recency_score == 0.0
        assert s.diversity_score == 0.0
        assert s.overall_likelihood == "minimal"
        assert isinstance(s.category_coverage, CategoryCoverage)

    def test_overall_likelihood_values(self):
        """All valid likelihood values can be set."""
        for val in ("minimal", "low", "medium", "high"):
            s = SummaryMetrics(overall_likelihood=val)
            assert s.overall_likelihood == val


class TestTokenlessSignal:
    def test_all_fields_serialize(self):
        signal = TokenlessSignal(
            protocol_id="morpho_base",
            protocol_name="Morpho",
            category="lending",
            protocol_weight=1.2,
            interacted=True,
            first_seen="2025-11-15",
            last_seen="2026-02-10",
            interaction_count=14,
            signal_types=["supply", "borrow"],
            signal_strength="strong",
            detection_mode="event_topic",
        )
        dumped = signal.model_dump()
        assert dumped["protocol_id"] == "morpho_base"
        assert dumped["interaction_count"] == 14
        assert dumped["signal_types"] == ["supply", "borrow"]

    def test_defaults(self):
        signal = TokenlessSignal(
            protocol_id="p",
            protocol_name="P",
            category="dex",
            protocol_weight=1.0,
            interacted=False,
            detection_mode="event_topic",
        )
        assert signal.first_seen is None
        assert signal.last_seen is None
        assert signal.interaction_count == 0
        assert signal.signal_types == []
        assert signal.signal_strength == "none"

    def test_signal_strength_values(self):
        for val in ("none", "weak", "moderate", "strong"):
            signal = TokenlessSignal(
                protocol_id="p", protocol_name="P", category="dex",
                protocol_weight=1.0, interacted=False, detection_mode="x",
                signal_strength=val,
            )
            assert signal.signal_strength == val


class TestTokenedSignal:
    def test_basic(self):
        signal = TokenedSignal(
            protocol_id="uni",
            protocol_name="Uniswap",
            category="dex",
            token_symbol="UNI",
            interacted=True,
            note="Has token",
        )
        assert signal.token_symbol == "UNI"
        assert signal.note == "Has token"

    def test_defaults(self):
        signal = TokenedSignal(
            protocol_id="p", protocol_name="P",
            category="dex", token_symbol="T",
            interacted=False,
        )
        assert signal.note == ""


class TestNextAction:
    def test_defaults(self):
        action = NextAction(action="Do something", reason="Because")
        assert action.suggested_protocols == []

    def test_full_action(self):
        action = NextAction(
            action="Interact with lending",
            reason="No lending coverage",
            suggested_protocols=["Morpho", "Aave"],
        )
        assert len(action.suggested_protocols) == 2
        assert action.action == "Interact with lending"


class TestSkippedProtocol:
    def test_basic(self):
        sp = SkippedProtocol(protocol_id="p1", reason="RPC budget exceeded")
        assert sp.protocol_id == "p1"
        assert sp.reason == "RPC budget exceeded"


class TestScanResponse:
    def test_minimal_response(self):
        resp = ScanResponse(
            address="0x" + "a" * 40,
            chain="base",
            scan_timestamp="2026-02-12T00:00:00+00:00",
            scan_window_days=90,
        )
        assert resp.scan_completeness == "full"
        assert resp.wallet_type == "eoa"
        assert resp.tokenless_signals == []
        assert resp.tokened_signals == []
        assert resp.next_actions == []
        assert resp.skipped_protocols == []
        assert resp.partial_scan_note is None
        assert resp.wallet_note is None
        assert resp.disclaimer == DISCLAIMER

    def test_full_response_serializes(self):
        resp = ScanResponse(
            address="0x" + "a" * 40,
            chain="base",
            scan_timestamp="2026-02-12T00:00:00+00:00",
            scan_window_days=90,
            wallet_type="contract",
            wallet_note="Smart contract wallet",
            scan_completeness="partial",
            partial_scan_note="Truncated",
        )
        dumped = resp.model_dump(by_alias=True)
        assert dumped["wallet_type"] == "contract"
        assert dumped["wallet_note"] == "Smart contract wallet"
        assert dumped["scan_completeness"] == "partial"
        assert dumped["partial_scan_note"] == "Truncated"
        # yield should be serialized as "yield" not "yield_"
        assert "yield" in dumped["summary"]["category_coverage"]

    def test_disclaimer_text(self):
        assert "not financial advice" in DISCLAIMER.lower()
        assert "onchain interaction patterns" in DISCLAIMER.lower()
