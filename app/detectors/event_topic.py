from __future__ import annotations

import logging

from app.config import settings
from app.detectors.base import BaseDetector, DetectionResult
from app.models.protocol import ContractEntry
from app.services.rpc import EvmRpcClient
from app.utils.address import pad_evm_address

logger = logging.getLogger("detector.event_topic")


class EventTopicDetector(BaseDetector):
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
        config = contract.detection_config
        if not config or not config.event_signatures:
            return DetectionResult(rpc_calls_used=0)

        result = DetectionResult()
        padded_user = pad_evm_address(user_address)

        for event_sig in config.event_signatures:
            if result.rpc_calls_used >= rpc_budget:
                break

            topic0 = event_sig.topic0
            user_position = event_sig.user_address_position

            # Build topics filter with user address in correct position
            topics: list[str | None] = [topic0]
            if user_position == "topic1":
                topics.append(padded_user)
            elif user_position == "topic2":
                topics.extend([None, padded_user])
            elif user_position == "topic3":
                topics.extend([None, None, padded_user])

            # Query in chunks (most recent first) to respect RPC limits
            chunk_size = settings.max_log_block_range
            chunk_end = to_block

            while chunk_end >= from_block and result.rpc_calls_used < rpc_budget:
                chunk_start = max(chunk_end - chunk_size + 1, from_block)

                try:
                    logs = await self._rpc.eth_get_logs(
                        {
                            "address": contract.address,
                            "fromBlock": hex(chunk_start),
                            "toBlock": hex(chunk_end),
                            "topics": topics,
                        }
                    )
                    result.rpc_calls_used += 1
                except Exception as e:
                    logger.warning(
                        f"eth_getLogs failed for {contract.address}: {e}"
                    )
                    result.rpc_calls_used += 1
                    chunk_end = chunk_start - 1
                    continue

                if logs:
                    result.interacted = True
                    result.interaction_count += len(logs)
                    if event_sig.interaction_type not in result.signal_types:
                        result.signal_types.append(event_sig.interaction_type)

                    block_nums = [int(log["blockNumber"], 16) for log in logs]
                    min_block = min(block_nums)
                    max_block = max(block_nums)
                    cur_first = int(result.first_seen) if result.first_seen else None
                    cur_last = int(result.last_seen) if result.last_seen else None
                    if cur_first is None or min_block < cur_first:
                        result.first_seen = str(min_block)
                    if cur_last is None or max_block > cur_last:
                        result.last_seen = str(max_block)

                chunk_end = chunk_start - 1

        return result
