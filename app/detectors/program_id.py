from __future__ import annotations

import logging

from app.detectors.base import DetectionResult
from app.models.protocol import ContractEntry

logger = logging.getLogger("detector.program_id")


class ProgramIdMatchDetector:
    """Detect Solana interactions by matching program IDs in parsed transactions.

    Unlike EVM detectors, this operates on pre-fetched and pre-parsed
    transactions rather than making its own RPC calls.
    """

    def detect_from_parsed_txs(
        self,
        contract: ContractEntry,
        parsed_txs: list[dict],
    ) -> DetectionResult:
        result = DetectionResult()
        program_id = contract.address.strip()

        config = contract.detection_config
        discriminators: set[str] = set()
        if config and config.instruction_discriminators:
            discriminators = set(config.instruction_discriminators)

        matching_txs = []
        for tx in parsed_txs:
            if _tx_involves_program(tx, program_id, discriminators):
                matching_txs.append(tx)

        if matching_txs:
            result.interacted = True
            result.interaction_count = len(matching_txs)

            # Extract interaction types from Helius parsed type field
            types_seen: set[str] = set()
            for tx in matching_txs:
                tx_type = tx.get("type", "unknown")
                types_seen.add(tx_type)
            result.signal_types = list(types_seen)

            # Extract timestamps for first/last seen
            timestamps: list[int] = []
            for tx in matching_txs:
                ts = tx.get("timestamp")
                if ts:
                    timestamps.append(ts)
            if timestamps:
                result.first_seen = str(min(timestamps))
                result.last_seen = str(max(timestamps))

        return result


def _tx_involves_program(
    tx: dict, program_id: str, discriminators: set[str]
) -> bool:
    """Check if a parsed transaction involves the given program ID.

    Works with both Helius enhanced format and raw jsonParsed format.
    """
    # Helius enhanced format: check instructions array
    for ix in tx.get("instructions", []):
        if ix.get("programId") == program_id:
            if discriminators:
                data = ix.get("data", "")
                if any(data.startswith(d) for d in discriminators):
                    return True
            else:
                return True
        # Check inner instructions
        for inner in ix.get("innerInstructions", []):
            if inner.get("programId") == program_id:
                return True

    # Helius enhanced format: check accountData for program involvement
    for acc in tx.get("accountData", []):
        if acc.get("account") == program_id:
            return True

    # Raw jsonParsed format fallback: check transaction.message.accountKeys
    message = tx.get("transaction", {}).get("message", {})
    for key in message.get("accountKeys", []):
        pubkey = key.get("pubkey", key) if isinstance(key, dict) else key
        if pubkey == program_id:
            return True

    return False
