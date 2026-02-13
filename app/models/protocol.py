from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class DetectionMode(str, Enum):
    EVENT_TOPIC = "event_topic"
    TRANSFER_TO_CONTRACT = "transfer_to_contract"
    TX_TO_CONTRACT = "tx_to_contract"
    PROGRAM_ID_MATCH = "program_id_match"
    HYBRID = "hybrid"


class ProtocolCategory(str, Enum):
    DEX = "dex"
    LENDING = "lending"
    BRIDGE = "bridge"
    NFT = "nft"
    SOCIAL = "social"
    GOVERNANCE = "governance"
    YIELD = "yield"
    PERPS = "perps"
    LIQUID_STAKING = "liquid_staking"
    ORACLE = "oracle"


class EventSignatureConfig(BaseModel):
    topic0: str
    user_address_position: str  # e.g. "topic1", "topic2"
    interaction_type: str


class DetectionConfig(BaseModel):
    # For event_topic mode
    event_signatures: list[EventSignatureConfig] | None = None
    # For transfer_to_contract mode
    token_contracts: list[str] | None = None
    interaction_type: str | None = None
    # For program_id_match mode (Solana)
    instruction_discriminators: list[str] | None = None
    # For hybrid mode
    sub_detectors: list[dict[str, Any]] | None = None


class ContractEntry(BaseModel):
    address: str
    label: str
    type: str  # e.g. "core", "vault", "router", "factory"
    detection_mode: DetectionMode
    detection_config: DetectionConfig


class AirdropIntel(BaseModel):
    confirmed_criteria: list[str] = []
    community_speculation: list[str] = []
    notable_events: list[str] = []
    last_reviewed: str | None = None


class ProtocolMetadata(BaseModel):
    website: str | None = None
    docs: str | None = None
    twitter: str | None = None


class Protocol(BaseModel):
    id: str
    name: str
    chain: str
    category: ProtocolCategory
    subcategory: str | None = None
    has_token: bool
    token_symbol: str | None = None
    status: str = "active"
    protocol_weight: float = 1.0
    contracts: list[ContractEntry] = []
    airdrop_intel: AirdropIntel = AirdropIntel()
    metadata: ProtocolMetadata = ProtocolMetadata()
    last_verified: str | None = None
