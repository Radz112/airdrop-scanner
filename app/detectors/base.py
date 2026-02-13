from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.models.protocol import ContractEntry


@dataclass
class DetectionResult:
    interacted: bool = False
    interaction_count: int = 0
    signal_types: list[str] = field(default_factory=list)
    first_seen: str | None = None
    last_seen: str | None = None
    rpc_calls_used: int = 0


class BaseDetector(ABC):
    @abstractmethod
    async def detect(
        self,
        user_address: str,
        contract: ContractEntry,
        from_block: int,
        to_block: int,
        rpc_budget: int,
    ) -> DetectionResult:
        ...
