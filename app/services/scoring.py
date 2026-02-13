from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models.response import (
    CategoryCoverage,
    NextAction,
    SummaryMetrics,
    TokenedSignal,
    TokenlessSignal,
)

logger = logging.getLogger("scoring")


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def calculate_strength(
    count: int,
    types: list[str],
    first_seen: str | None,
    last_seen: str | None,
    protocol_weight: float,
) -> str:
    """Multi-factor signal strength: count + diversity + recency + duration, scaled by weight."""
    if count == 0:
        return "none"

    now = _now_utc()
    type_diversity = len({t for t in types if t != "unknown_interaction"})
    parsed_first = _parse_date(first_seen)
    parsed_last = _parse_date(last_seen)
    days_since_last = (now - parsed_last).days if parsed_last else 999

    score = 0

    # Interaction count (0-3 pts)
    if count >= 10:
        score += 3
    elif count >= 5:
        score += 2
    elif count >= 2:
        score += 1

    # Type diversity (0-3 pts)
    if type_diversity >= 3:
        score += 3
    elif type_diversity >= 2:
        score += 2
    elif type_diversity >= 1:
        score += 1

    # Recency (0-3 pts)
    if days_since_last <= 7:
        score += 3
    elif days_since_last <= 30:
        score += 2
    elif days_since_last <= 90:
        score += 1

    # Duration (0-1 pt)
    if parsed_first and parsed_last and (parsed_last - parsed_first).days >= 30:
        score += 1

    score *= protocol_weight

    if score >= 7:
        return "strong"
    if score >= 4:
        return "moderate"
    if score >= 1:
        return "weak"
    return "none"


def build_summary(
    tokenless_signals: list[TokenlessSignal],
    tokened_signals: list[TokenedSignal],
) -> SummaryMetrics:
    """Only tokenless protocols drive overall likelihood."""
    all_signals = tokenless_signals + tokened_signals

    tokenless_interacted = [s for s in tokenless_signals if s.interacted]
    all_interacted = [s for s in all_signals if s.interacted]

    # Recency score (tokenless only, 180-day decay)
    now = _now_utc()
    if tokenless_interacted:
        recency_values = []
        for s in tokenless_interacted:
            parsed = _parse_date(s.last_seen)
            recency_values.append(
                max(0.0, 1.0 - ((now - parsed).days / 180.0)) if parsed else 0.0
            )
        recency_score = round(sum(recency_values) / len(recency_values), 2)
    else:
        recency_score = 0.0

    # Diversity score (all protocols)
    all_categories = {s.category for s in all_signals}
    interacted_categories = {s.category for s in all_interacted}
    diversity_score = round(
        len(interacted_categories) / max(len(all_categories), 1), 2
    )

    # Overall likelihood (tokenless only)
    tc = len(tokenless_interacted)
    if tc >= 5 and recency_score >= 0.5 and diversity_score >= 0.5:
        likelihood = "high"
    elif tc >= 2 and (recency_score >= 0.3 or diversity_score >= 0.3):
        likelihood = "medium"
    elif tc >= 1:
        likelihood = "low"
    else:
        likelihood = "minimal"

    return SummaryMetrics(
        tokenless_protocols_interacted=tc,
        tokenless_protocols_available=len(tokenless_signals),
        total_protocols_scanned=len(all_signals),
        recency_score=recency_score,
        diversity_score=diversity_score,
        overall_likelihood=likelihood,
        category_coverage=_build_coverage(all_interacted),
    )


def _build_coverage(interacted_signals: list) -> CategoryCoverage:
    hit = {s.category for s in interacted_signals}
    return CategoryCoverage(**{
        ("yield_" if c == "yield" else c): c in hit
        for c in ("dex", "lending", "bridge", "nft", "social",
                   "governance", "yield", "perps", "liquid_staking", "oracle")
    })


def generate_next_actions(
    summary: SummaryMetrics,
    tokenless_signals: list[TokenlessSignal],
    chain: str,
) -> list[NextAction]:
    """Suggest up to 3 actions for uncovered categories."""
    coverage_dict = summary.category_coverage.model_dump(by_alias=True)
    actions: list[NextAction] = []

    for category, covered in coverage_dict.items():
        if covered:
            continue

        candidates = sorted(
            [s for s in tokenless_signals if s.category == category and not s.interacted],
            key=lambda s: s.protocol_weight,
            reverse=True,
        )
        if not candidates:
            continue

        actions.append(
            NextAction(
                action=f"Interact with a {category} protocol on {chain.title()}",
                reason=(
                    f"You have no {category} interactions — "
                    f"this category is commonly included in airdrop criteria"
                ),
                suggested_protocols=[c.protocol_name for c in candidates[:2]],
            )
        )

    return actions[:3]
