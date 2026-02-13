from __future__ import annotations

import logging

from app.config import settings
from app.detectors.base import BaseDetector, DetectionResult
from app.models.protocol import ContractEntry
from app.services.rpc import EvmRpcClient
from app.utils.address import pad_evm_address

logger = logging.getLogger("detector.transfer_to")

# ERC-20 Transfer(address indexed from, address indexed to, uint256 value)
TRANSFER_TOPIC0 = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)


class TransferToContractDetector(BaseDetector):
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
        if not config or not config.token_contracts:
            return DetectionResult(rpc_calls_used=0)

        result = DetectionResult()
        padded_user = pad_evm_address(user_address)
        padded_contract = pad_evm_address(contract.address)

        chunk_size = settings.max_log_block_range

        for token_addr in config.token_contracts:
            if result.rpc_calls_used >= rpc_budget:
                break

            # Query in chunks (most recent first) to respect RPC limits
            chunk_end_cur = to_block
            all_logs: list[dict] = []

            while chunk_end_cur >= from_block and result.rpc_calls_used < rpc_budget:
                chunk_start_cur = max(chunk_end_cur - chunk_size + 1, from_block)
                try:
                    chunk_logs = await self._rpc.eth_get_logs(
                        {
                            "address": token_addr,
                            "fromBlock": hex(chunk_start_cur),
                            "toBlock": hex(chunk_end_cur),
                            "topics": [TRANSFER_TOPIC0, padded_user, padded_contract],
                        }
                    )
                    result.rpc_calls_used += 1
                    all_logs.extend(chunk_logs)
                except Exception as e:
                    logger.warning(
                        f"eth_getLogs failed for Transfer to {contract.address}: {e}"
                    )
                    result.rpc_calls_used += 1
                chunk_end_cur = chunk_start_cur - 1

            logs = all_logs
            if logs:
                result.interacted = True
                result.interaction_count += len(logs)
                interaction_type = config.interaction_type or "token_transfer"
                if interaction_type not in result.signal_types:
                    result.signal_types.append(interaction_type)

                block_nums = [int(log["blockNumber"], 16) for log in logs]
                min_block = min(block_nums)
                max_block = max(block_nums)
                cur_first = int(result.first_seen) if result.first_seen else None
                cur_last = int(result.last_seen) if result.last_seen else None
                if cur_first is None or min_block < cur_first:
                    result.first_seen = str(min_block)
                if cur_last is None or max_block > cur_last:
                    result.last_seen = str(max_block)

        return result
