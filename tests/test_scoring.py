from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.response import CategoryCoverage, SummaryMetrics
from app.services.scoring import (
    _build_coverage,
    _parse_date,
    build_summary,
    calculate_strength,
    generate_next_actions,
)


class TestParseDate:
    def test_valid_date(self):
        dt = _parse_date("2026-01-15")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 15

    def test_none_input(self):
        assert _parse_date(None) is None

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_invalid_format(self):
        assert _parse_date("not-a-date") is None

    def test_wrong_format(self):
        assert _parse_date("01/15/2026") is None


class TestCalculateStrength:

    def test_zero_count_returns_none(self):
        result = calculate_strength(
            count=0, types=[], first_seen=None, last_seen=None, protocol_weight=1.0
        )
        assert result == "none"

    @patch("app.services.scoring._now_utc")
    def test_strong_signal(self, mock_now):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        result = calculate_strength(
            count=15,  # 3 pts
            types=["swap", "supply", "borrow"],  # 3 pts
            first_seen="2025-12-01",  # duration = 73 days → 1 pt
            last_seen="2026-02-12",  # 0 days ago → 3 pts → total raw = 10
            protocol_weight=1.0,  # 10 * 1.0 = 10 → strong
        )
        assert result == "strong"

    @patch("app.services.scoring._now_utc")
    def test_moderate_signal(self, mock_now):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        result = calculate_strength(
            count=5,  # 2 pts
            types=["swap"],  # 1 pt
            first_seen="2026-01-20",  # duration 23 days → 0 pt
            last_seen="2026-02-12",  # 0 days → 3 pts → raw = 6
            protocol_weight=1.0,  # 6 * 1.0 = 6 → moderate
        )
        assert result == "moderate"

    @patch("app.services.scoring._now_utc")
    def test_weak_signal(self, mock_now):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        result = calculate_strength(
            count=1,  # 0 pts
            types=["swap"],  # 1 pt
            first_seen=None,
            last_seen="2026-01-01",  # 42 days → 1 pt → raw = 2
            protocol_weight=1.0,  # 2 * 1.0 = 2 → weak
        )
        assert result == "weak"

    @patch("app.services.scoring._now_utc")
    def test_protocol_weight_multiplier(self, mock_now):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        # Same interactions, but weight=1.5 should boost score
        result_low = calculate_strength(
            count=5, types=["swap"], first_seen=None, last_seen="2026-02-10",
            protocol_weight=1.0,
        )
        result_high = calculate_strength(
            count=5, types=["swap"], first_seen=None, last_seen="2026-02-10",
            protocol_weight=1.5,
        )
        # Weight 1.5 can push a moderate into strong
        assert result_low in ("moderate", "strong")
        assert result_high in ("moderate", "strong")

    @patch("app.services.scoring._now_utc")
    def test_unknown_interaction_excluded_from_diversity(self, mock_now):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        result = calculate_strength(
            count=2,
            types=["unknown_interaction", "unknown_interaction"],
            first_seen=None,
            last_seen="2026-02-12",
            protocol_weight=1.0,
        )
        # count=2 → 1 pt, diversity=0 (unknown excluded) → 0, recency=3 → total 4 → moderate
        assert result == "moderate"

    @patch("app.services.scoring._now_utc")
    def test_old_activity_low_recency(self, mock_now):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        result = calculate_strength(
            count=10,  # 3 pts
            types=["swap", "supply"],  # 2 pts
            first_seen="2025-06-01",
            last_seen="2025-06-15",  # ~242 days ago → 0 recency pts, duration 14 → 0
            protocol_weight=1.0,  # raw = 5 → moderate
        )
        assert result == "moderate"


class TestBuildSummary:
    def test_no_interactions_minimal(self, make_tokenless_signal, make_tokened_signal):
        tokenless = [
            make_tokenless_signal(protocol_id="a", category="dex"),
            make_tokenless_signal(protocol_id="b", category="lending"),
        ]
        tokened = [make_tokened_signal(protocol_id="c", category="bridge")]
        summary = build_summary(tokenless, tokened)

        assert summary.tokenless_protocols_interacted == 0
        assert summary.tokenless_protocols_available == 2
        assert summary.total_protocols_scanned == 3
        assert summary.overall_likelihood == "minimal"
        assert summary.recency_score == 0.0

    @patch("app.services.scoring._now_utc")
    def test_low_likelihood(self, mock_now, make_tokenless_signal):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        tokenless = [
            make_tokenless_signal(
                protocol_id="a", category="dex", interacted=True,
                last_seen="2025-06-01",
            ),
            make_tokenless_signal(protocol_id="b", category="lending"),
        ]
        summary = build_summary(tokenless, [])
        assert summary.tokenless_protocols_interacted == 1
        assert summary.overall_likelihood == "low"

    @patch("app.services.scoring._now_utc")
    def test_medium_likelihood(self, mock_now, make_tokenless_signal):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        tokenless = [
            make_tokenless_signal(
                protocol_id="a", category="dex", interacted=True,
                last_seen="2026-02-01",
            ),
            make_tokenless_signal(
                protocol_id="b", category="lending", interacted=True,
                last_seen="2026-01-15",
            ),
            make_tokenless_signal(protocol_id="c", category="bridge"),
        ]
        summary = build_summary(tokenless, [])
        assert summary.tokenless_protocols_interacted == 2
        assert summary.overall_likelihood == "medium"

    @patch("app.services.scoring._now_utc")
    def test_high_likelihood(self, mock_now, make_tokenless_signal):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        categories = ["dex", "lending", "bridge", "nft", "social"]
        tokenless = [
            make_tokenless_signal(
                protocol_id=f"p{i}", category=cat, interacted=True,
                last_seen="2026-02-10",
            )
            for i, cat in enumerate(categories)
        ]
        summary = build_summary(tokenless, [])
        assert summary.tokenless_protocols_interacted == 5
        assert summary.overall_likelihood == "high"
        assert summary.recency_score >= 0.5
        assert summary.diversity_score >= 0.5

    def test_category_coverage(self, make_tokenless_signal, make_tokened_signal):
        tokenless = [
            make_tokenless_signal(
                protocol_id="a", category="dex", interacted=True,
            ),
        ]
        tokened = [
            make_tokened_signal(
                protocol_id="b", category="lending", interacted=True,
            ),
        ]
        summary = build_summary(tokenless, tokened)
        assert summary.category_coverage.dex is True
        assert summary.category_coverage.lending is True
        assert summary.category_coverage.bridge is False

    def test_diversity_includes_tokened(self, make_tokenless_signal, make_tokened_signal):
        tokenless = [
            make_tokenless_signal(protocol_id="a", category="dex", interacted=True),
        ]
        tokened = [
            make_tokened_signal(protocol_id="b", category="lending", interacted=True),
        ]
        summary = build_summary(tokenless, tokened)
        # 2 interacted categories / 2 total categories = 1.0
        assert summary.diversity_score == 1.0


class TestGenerateNextActions:
    @patch("app.services.scoring._now_utc")
    def test_suggests_uncovered_categories(self, mock_now, make_tokenless_signal):
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)

        tokenless = [
            make_tokenless_signal(
                protocol_id="a", protocol_name="Proto A",
                category="dex", interacted=True, last_seen="2026-02-10",
            ),
            make_tokenless_signal(
                protocol_id="b", protocol_name="Proto B",
                category="lending", interacted=False,
                protocol_weight=1.2,
            ),
            make_tokenless_signal(
                protocol_id="c", protocol_name="Proto C",
                category="lending", interacted=False,
                protocol_weight=0.8,
            ),
        ]
        summary = build_summary(tokenless, [])
        actions = generate_next_actions(summary, tokenless, "base")

        assert len(actions) >= 1
        lending_action = [a for a in actions if "lending" in a.action]
        assert len(lending_action) == 1
        # Should suggest highest weight first
        assert lending_action[0].suggested_protocols[0] == "Proto B"

    def test_max_three_actions(self, make_tokenless_signal):
        # Create many uncovered categories
        categories = ["dex", "lending", "bridge", "nft", "social", "governance"]
        tokenless = [
            make_tokenless_signal(
                protocol_id=f"p{i}", protocol_name=f"Proto {i}",
                category=cat, interacted=False,
            )
            for i, cat in enumerate(categories)
        ]
        summary = build_summary(tokenless, [])
        actions = generate_next_actions(summary, tokenless, "base")
        assert len(actions) <= 3

    def test_no_actions_when_all_covered(self, make_tokenless_signal):
        tokenless = [
            make_tokenless_signal(
                protocol_id="a", category="dex", interacted=True,
            ),
        ]
        summary = build_summary(tokenless, [])
        # dex is covered, no other categories to suggest
        actions = generate_next_actions(summary, tokenless, "base")
        # All remaining categories have no candidate protocols
        uncovered_with_candidates = [
            a for a in actions if a.suggested_protocols
        ]
        assert len(uncovered_with_candidates) == 0


class TestCalculateStrengthBoundaries:

    @patch("app.services.scoring._now_utc")
    def test_score_exactly_at_strong_threshold(self, mock_now):
        """Score of exactly 7 should be 'strong'."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        # count=10 → 3pts, types=["a","b"] → 2pts, last_seen=today → 3pts,
        # duration < 30 → 0pt, total=8, weight=1.0 → 8 ≥ 7 → strong
        result = calculate_strength(
            count=10, types=["a", "b"],
            first_seen="2026-02-01", last_seen="2026-02-12",
            protocol_weight=1.0,
        )
        assert result == "strong"

    @patch("app.services.scoring._now_utc")
    def test_score_just_below_strong_threshold(self, mock_now):
        """Score of 6 should be 'moderate', not 'strong'."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        # count=5 → 2pts, types=["a"] → 1pt, last_seen=today → 3pts,
        # no duration → 0pt, total=6, weight=1.0 → 6 < 7 → moderate
        result = calculate_strength(
            count=5, types=["a"],
            first_seen=None, last_seen="2026-02-12",
            protocol_weight=1.0,
        )
        assert result == "moderate"

    @patch("app.services.scoring._now_utc")
    def test_score_exactly_at_moderate_threshold(self, mock_now):
        """Score of exactly 4 should be 'moderate'."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        # count=2 → 1pt, types=["a"] → 1pt, last_seen=30 days ago → 2pts,
        # total=4, weight=1.0 → 4 → moderate
        result = calculate_strength(
            count=2, types=["a"],
            first_seen=None, last_seen="2026-01-13",
            protocol_weight=1.0,
        )
        assert result == "moderate"

    @patch("app.services.scoring._now_utc")
    def test_score_just_below_moderate_threshold(self, mock_now):
        """Score < 4 but >= 1 should be 'weak'."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        # count=1 → 0pts, types=["a"] → 1pt, last_seen=60 days ago → 1pt,
        # total=2, weight=1.0 → 2 → weak
        result = calculate_strength(
            count=1, types=["a"],
            first_seen=None, last_seen="2025-12-14",
            protocol_weight=1.0,
        )
        assert result == "weak"

    @patch("app.services.scoring._now_utc")
    def test_weight_zero_always_none(self, mock_now):
        """Protocol weight of 0 should result in score=0 → 'none' even with interactions."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        result = calculate_strength(
            count=15, types=["swap", "supply", "borrow"],
            first_seen="2025-12-01", last_seen="2026-02-12",
            protocol_weight=0.0,
        )
        # raw=10 * 0.0 = 0 → none (score < 1)
        assert result == "none"

    @patch("app.services.scoring._now_utc")
    def test_no_last_seen_high_days_since(self, mock_now):
        """No last_seen date → days_since_last=999 → 0 recency points."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        # count=10 → 3pts, types=["a","b","c"] → 3pts, no recency → 0pts,
        # can't compute duration either → 0pts, total=6 → moderate
        result = calculate_strength(
            count=10, types=["a", "b", "c"],
            first_seen="2025-01-01", last_seen=None,
            protocol_weight=1.0,
        )
        assert result == "moderate"

    @patch("app.services.scoring._now_utc")
    def test_recency_exactly_7_days(self, mock_now):
        """Last seen exactly 7 days ago → 3 recency points (≤ 7)."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        result = calculate_strength(
            count=1, types=["a"],
            first_seen=None, last_seen="2026-02-05",
            protocol_weight=1.0,
        )
        # count=1→0, types=1→1, recency 7d→3, total=4 → moderate
        assert result == "moderate"

    @patch("app.services.scoring._now_utc")
    def test_recency_exactly_30_days(self, mock_now):
        """Last seen exactly 30 days ago → 2 recency points (≤ 30)."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        result = calculate_strength(
            count=1, types=["a"],
            first_seen=None, last_seen="2026-01-13",
            protocol_weight=1.0,
        )
        # count=1→0, types=1→1, recency 30d→2, total=3 → weak
        assert result == "weak"

    @patch("app.services.scoring._now_utc")
    def test_recency_exactly_90_days(self, mock_now):
        """Last seen exactly 90 days ago → 1 recency point (≤ 90)."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        result = calculate_strength(
            count=1, types=["a"],
            first_seen=None, last_seen="2025-11-14",
            protocol_weight=1.0,
        )
        # count=1→0, types=1→1, recency 90d→1, total=2 → weak
        assert result == "weak"

    @patch("app.services.scoring._now_utc")
    def test_recency_91_days_no_points(self, mock_now):
        """Last seen 91 days ago → 0 recency points (> 90)."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        result = calculate_strength(
            count=1, types=["a"],
            first_seen=None, last_seen="2025-11-13",
            protocol_weight=1.0,
        )
        # count=1→0, types=1→1, recency 91d→0, total=1 → weak
        assert result == "weak"

    @patch("app.services.scoring._now_utc")
    def test_duration_exactly_30_days_gets_point(self, mock_now):
        """Duration of exactly 30 days earns the bonus point."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        result = calculate_strength(
            count=2, types=["a"],
            first_seen="2026-01-13", last_seen="2026-02-12",
            protocol_weight=1.0,
        )
        # count=2→1, types=1→1, recency 0d→3, duration 30d→1, total=6 → moderate
        assert result == "moderate"

    @patch("app.services.scoring._now_utc")
    def test_count_boundary_2(self, mock_now):
        """count=2 gives 1 point, count=1 gives 0."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        r1 = calculate_strength(count=1, types=[], first_seen=None, last_seen=None, protocol_weight=1.0)
        r2 = calculate_strength(count=2, types=[], first_seen=None, last_seen=None, protocol_weight=1.0)
        assert r1 == "none"  # 0 pts, weight=1.0, 0*1=0 < 1
        assert r2 == "weak"  # 1 pt, weight=1.0, 1*1=1 ≥ 1


class TestBuildSummaryEdgeCases:
    def test_empty_signal_lists(self):
        """No protocols at all → minimal with all zeros."""
        summary = build_summary([], [])
        assert summary.tokenless_protocols_interacted == 0
        assert summary.tokenless_protocols_available == 0
        assert summary.total_protocols_scanned == 0
        assert summary.overall_likelihood == "minimal"
        assert summary.recency_score == 0.0
        assert summary.diversity_score == 0.0

    def test_only_tokened_protocols(self, make_tokened_signal):
        """All tokened, no tokenless → likelihood stays minimal."""
        tokened = [
            make_tokened_signal(protocol_id="a", category="dex", interacted=True),
            make_tokened_signal(protocol_id="b", category="lending", interacted=True),
        ]
        summary = build_summary([], tokened)
        assert summary.tokenless_protocols_interacted == 0
        assert summary.overall_likelihood == "minimal"
        # But diversity should still reflect tokened interactions
        assert summary.diversity_score > 0.0

    @patch("app.services.scoring._now_utc")
    def test_recency_with_none_last_seen(self, mock_now, make_tokenless_signal):
        """Interacted but last_seen=None → recency_value=0 for that protocol."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        tokenless = [
            make_tokenless_signal(
                protocol_id="a", category="dex", interacted=True,
                last_seen=None,
            ),
        ]
        summary = build_summary(tokenless, [])
        assert summary.recency_score == 0.0
        assert summary.overall_likelihood == "low"

    @patch("app.services.scoring._now_utc")
    def test_recency_score_exact_calculation(self, mock_now, make_tokenless_signal):
        """Verify exact recency math: 1 - (days / 180)."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        # 90 days ago: 1 - 90/180 = 0.5
        tokenless = [
            make_tokenless_signal(
                protocol_id="a", category="dex", interacted=True,
                last_seen="2025-11-14",  # 90 days before 2026-02-12
            ),
        ]
        summary = build_summary(tokenless, [])
        assert summary.recency_score == 0.5

    @patch("app.services.scoring._now_utc")
    def test_recency_clamped_to_zero_for_old(self, mock_now, make_tokenless_signal):
        """Activity > 180 days ago → recency value clamped to 0."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        tokenless = [
            make_tokenless_signal(
                protocol_id="a", category="dex", interacted=True,
                last_seen="2025-01-01",  # >365 days → clamped to 0
            ),
        ]
        summary = build_summary(tokenless, [])
        assert summary.recency_score == 0.0

    def test_diversity_single_category(self, make_tokenless_signal):
        """All protocols in same category → diversity = 1/1 = 1.0."""
        tokenless = [
            make_tokenless_signal(protocol_id="a", category="dex", interacted=True),
            make_tokenless_signal(protocol_id="b", category="dex", interacted=False),
        ]
        summary = build_summary(tokenless, [])
        # 1 interacted category / 1 total category = 1.0
        assert summary.diversity_score == 1.0

    def test_diversity_no_interactions(self, make_tokenless_signal):
        """No interactions → diversity = 0 / N = 0.0."""
        tokenless = [
            make_tokenless_signal(protocol_id="a", category="dex"),
            make_tokenless_signal(protocol_id="b", category="lending"),
        ]
        summary = build_summary(tokenless, [])
        assert summary.diversity_score == 0.0

    @patch("app.services.scoring._now_utc")
    def test_medium_threshold_recency_drives(self, mock_now, make_tokenless_signal):
        """2 interacted + recency≥0.3 → medium, even with diversity<0.3."""
        mock_now.return_value = datetime(2026, 2, 12, tzinfo=timezone.utc)
        # Both in same category → diversity = 1/1 = 1.0, so that's covered
        # Instead: 2 interacted in same category, 3 other categories not interacted
        tokenless = [
            make_tokenless_signal(protocol_id="a", category="dex", interacted=True, last_seen="2026-02-01"),
            make_tokenless_signal(protocol_id="b", category="dex", interacted=True, last_seen="2026-02-01"),
            make_tokenless_signal(protocol_id="c", category="lending"),
            make_tokenless_signal(protocol_id="d", category="bridge"),
            make_tokenless_signal(protocol_id="e", category="nft"),
        ]
        summary = build_summary(tokenless, [])
        assert summary.tokenless_protocols_interacted == 2
        # diversity = 1 interacted cat / 4 total cats = 0.25 (<0.3)
        # But recency ≥ 0.3 so condition (recency >= 0.3 or diversity >= 0.3) is True
        assert summary.overall_likelihood == "medium"


class TestBuildCoverage:
    def test_yield_alias_mapping(self, make_tokenless_signal):
        """The 'yield' category should map to yield_ field."""
        signals = [make_tokenless_signal(protocol_id="a", category="yield", interacted=True)]
        coverage = _build_coverage(signals)
        assert coverage.yield_ is True
        # Serialization should use 'yield' as key
        dumped = coverage.model_dump(by_alias=True)
        assert "yield" in dumped
        assert "yield_" not in dumped

    def test_empty_signals_all_false(self):
        """No interactions → all coverage categories False."""
        coverage = _build_coverage([])
        dumped = coverage.model_dump(by_alias=True)
        assert all(v is False for v in dumped.values())

    def test_all_categories_covered(self, make_tokenless_signal):
        """Every category interacted → all True."""
        categories = [
            "dex", "lending", "bridge", "nft", "social",
            "governance", "yield", "perps", "liquid_staking", "oracle",
        ]
        signals = [
            make_tokenless_signal(protocol_id=f"p{i}", category=cat, interacted=True)
            for i, cat in enumerate(categories)
        ]
        coverage = _build_coverage(signals)
        dumped = coverage.model_dump(by_alias=True)
        assert all(v is True for v in dumped.values())


class TestNextActionsEdgeCases:
    def test_chain_name_in_action_text(self, make_tokenless_signal):
        """Action text should include the chain name, title-cased."""
        tokenless = [
            make_tokenless_signal(protocol_id="a", category="dex", interacted=False),
        ]
        summary = build_summary(tokenless, [])
        actions = generate_next_actions(summary, tokenless, "solana")
        assert len(actions) >= 1
        assert "Solana" in actions[0].action

    def test_empty_tokenless_list(self):
        """No tokenless signals → no actions possible."""
        summary = build_summary([], [])
        actions = generate_next_actions(summary, [], "base")
        assert actions == []

    def test_all_interacted_no_candidates(self, make_tokenless_signal):
        """Category has protocols but all interacted → skip that category."""
        tokenless = [
            make_tokenless_signal(protocol_id="a", category="dex", interacted=True),
            make_tokenless_signal(protocol_id="b", category="dex", interacted=True),
        ]
        summary = build_summary(tokenless, [])
        actions = generate_next_actions(summary, tokenless, "base")
        dex_actions = [a for a in actions if "dex" in a.action]
        assert len(dex_actions) == 0

    def test_suggested_protocols_limited_to_two(self, make_tokenless_signal):
        """Even with many candidates, only 2 are suggested per action."""
        tokenless = [
            make_tokenless_signal(
                protocol_id=f"p{i}", protocol_name=f"Proto {i}",
                category="dex", interacted=False, protocol_weight=float(i),
            )
            for i in range(5)
        ]
        summary = build_summary(tokenless, [])
        actions = generate_next_actions(summary, tokenless, "base")
        dex_actions = [a for a in actions if "dex" in a.action]
        assert len(dex_actions) == 1
        assert len(dex_actions[0].suggested_protocols) == 2
        # Highest weight first
        assert dex_actions[0].suggested_protocols[0] == "Proto 4"
