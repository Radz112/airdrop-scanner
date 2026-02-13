from __future__ import annotations

from pydantic import BaseModel, Field


class TokenlessSignal(BaseModel):
    protocol_id: str
    protocol_name: str
    category: str
    protocol_weight: float
    interacted: bool
    first_seen: str | None = None
    last_seen: str | None = None
    interaction_count: int = 0
    signal_types: list[str] = []
    signal_strength: str = "none"  # none, weak, moderate, strong
    detection_mode: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "protocol_id": "morpho_base",
                "protocol_name": "Morpho",
                "category": "lending",
                "protocol_weight": 1.2,
                "interacted": True,
                "first_seen": "2025-11-15",
                "last_seen": "2026-02-10",
                "interaction_count": 14,
                "signal_types": ["supply", "borrow"],
                "signal_strength": "strong",
                "detection_mode": "event_topic",
            }
        }
    }


class TokenedSignal(BaseModel):
    protocol_id: str
    protocol_name: str
    category: str
    token_symbol: str
    interacted: bool
    note: str = ""


class CategoryCoverage(BaseModel):
    dex: bool = False
    lending: bool = False
    bridge: bool = False
    nft: bool = False
    social: bool = False
    governance: bool = False
    yield_: bool = Field(default=False, alias="yield")
    perps: bool = False
    liquid_staking: bool = False
    oracle: bool = False

    model_config = {"populate_by_name": True}


class SummaryMetrics(BaseModel):
    tokenless_protocols_interacted: int = 0
    tokenless_protocols_available: int = 0
    total_protocols_scanned: int = 0
    recency_score: float = 0.0
    diversity_score: float = 0.0
    overall_likelihood: str = "minimal"  # minimal, low, medium, high
    category_coverage: CategoryCoverage = CategoryCoverage()


class NextAction(BaseModel):
    action: str
    reason: str
    suggested_protocols: list[str] = []


DISCLAIMER = (
    "This reflects onchain interaction patterns only. Actual airdrop eligibility "
    "is determined solely by each protocol and may include factors not captured "
    "here, including offchain activity, snapshots at specific dates, sybil "
    "filtering, and minimum thresholds. This is not financial advice."
)


class SkippedProtocol(BaseModel):
    protocol_id: str
    reason: str


class ScanResponse(BaseModel):
    address: str
    chain: str
    scan_timestamp: str
    scan_completeness: str = "full"  # full, partial, error
    scan_window_days: int
    wallet_type: str = "eoa"  # eoa, contract, unknown

    tokenless_signals: list[TokenlessSignal] = []
    tokened_signals: list[TokenedSignal] = []
    summary: SummaryMetrics = SummaryMetrics()
    next_actions: list[NextAction] = []
    skipped_protocols: list[SkippedProtocol] = []
    partial_scan_note: str | None = None
    wallet_note: str | None = None
    disclaimer: str = DISCLAIMER
