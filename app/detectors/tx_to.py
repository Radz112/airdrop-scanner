from __future__ import annotations

import logging

from app.config import settings
from app.detectors.base import BaseDetector, DetectionResult
from app.models.protocol import ContractEntry
from app.services.rpc import EvmRpcClient
from app.utils.address import pad_evm_address

logger = logging.getLogger("detector.tx_to")


class TxToContractDetector(BaseDetector):
    """Detect any interaction with a contract via broad event log filtering.

    Searches for ANY event emitted by the contract where the user's address
    appears as topic1 or topic2. This is a catch-all detector for protocols
    where we don't have specific event signatures configured.
    """

    def __init__(self, rpc_client: EvmRpcClient):
        self._rpc = rpc_client

    async def detect(
        self,
        user_address: str,
        contract: ContractEntry,
        from_block: int,
        to_block: int,
        rpc_budget: int,
    ) -> DetectionResult:
        result = DetectionResult()
        padded_user = pad_evm_address(user_address)
        logs1: list[dict] = []
        logs2: list[dict] = []

        chunk_size = settings.max_log_block_range

        # Query 1: Any event from the contract with user as topic1 (most recent first)
        chunk_end_1 = to_block
        while chunk_end_1 >= from_block and result.rpc_calls_used < rpc_budget:
            chunk_start_1 = max(chunk_end_1 - chunk_size + 1, from_block)
            try:
                chunk_logs = await self._rpc.eth_get_logs(
                    {
                        "address": contract.address,
                        "fromBlock": hex(chunk_start_1),
                        "toBlock": hex(chunk_end_1),
                        "topics": [None, padded_user],
                    }
                )
                result.rpc_calls_used += 1
                logs1.extend(chunk_logs)
            except Exception as e:
                logger.warning(
                    f"eth_getLogs (topic1) failed for {contract.address}: {e}"
                )
                result.rpc_calls_used += 1
            chunk_end_1 = chunk_start_1 - 1

        # Query 2: Any event from the contract with user as topic2 (most recent first)
        chunk_end_2 = to_block
        while chunk_end_2 >= from_block and result.rpc_calls_used < rpc_budget:
            chunk_start_2 = max(chunk_end_2 - chunk_size + 1, from_block)
            try:
                chunk_logs = await self._rpc.eth_get_logs(
                    {
                        "address": contract.address,
                        "fromBlock": hex(chunk_start_2),
                        "toBlock": hex(chunk_end_2),
                        "topics": [None, None, padded_user],
                    }
                )
                result.rpc_calls_used += 1
                logs2.extend(chunk_logs)
            except Exception as e:
                logger.warning(
                    f"eth_getLogs (topic2) failed for {contract.address}: {e}"
                )
                result.rpc_calls_used += 1
            chunk_end_2 = chunk_start_2 - 1

        # Deduplicate by transaction hash
        seen_txs: set[str] = set()
        all_logs: list[dict] = []
        for log in logs1 + logs2:
            tx_hash = log.get("transactionHash")
            if tx_hash and tx_hash not in seen_txs:
                seen_txs.add(tx_hash)
                all_logs.append(log)

        if all_logs:
            result.interacted = True
            result.interaction_count = len(all_logs)
            result.signal_types.append("contract_interaction")

            block_nums = [int(log["blockNumber"], 16) for log in all_logs]
            result.first_seen = str(min(block_nums))
            result.last_seen = str(max(block_nums))

        return result
