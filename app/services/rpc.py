from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("rpc")

# Permanent block timestamp cache (block timestamps are immutable)
_block_ts_cache: dict[int, int] = {}


class EvmRpcClient:
    def __init__(self, rpc_url: str):
        self._url = rpc_url
        self._id = 0
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def _call(self, method: str, params: list | None = None) -> Any:
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
            "id": self._id,
        }
        client = self._get_client()
        resp = await client.post(self._url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data.get("result")

    async def eth_block_number(self) -> int:
        result = await self._call("eth_blockNumber")
        return int(result, 16)

    async def eth_get_logs(self, params: dict) -> list[dict]:
        result = await self._call("eth_getLogs", [params])
        return result or []

    async def eth_get_block_by_number(self, block_num: int) -> dict:
        hex_block = hex(block_num)
        result = await self._call("eth_getBlockByNumber", [hex_block, False])
        return result or {}

    async def eth_get_code(self, address: str) -> str:
        """Get contract code at address. Returns '0x' for EOAs."""
        result = await self._call("eth_getCode", [address, "latest"])
        return result or "0x"

    async def get_block_timestamp(self, block_num: int) -> int:
        if block_num in _block_ts_cache:
            return _block_ts_cache[block_num]
        block = await self.eth_get_block_by_number(block_num)
        ts = int(block.get("timestamp", "0x0"), 16)
        _block_ts_cache[block_num] = ts
        return ts

    async def batch_get_block_timestamps(
        self, block_numbers: set[int]
    ) -> dict[int, int]:
        result = {}
        to_fetch = []
        for bn in block_numbers:
            if bn in _block_ts_cache:
                result[bn] = _block_ts_cache[bn]
            else:
                to_fetch.append(bn)

        if to_fetch:
            timestamps = await asyncio.gather(
                *(self.get_block_timestamp(bn) for bn in to_fetch)
            )
            for bn, ts in zip(to_fetch, timestamps):
                result[bn] = ts

        return result


async def compute_scan_window(
    rpc: EvmRpcClient, window_days: int
) -> dict:
    """Convert a day-based window to a block range via binary search."""
    window_days = max(
        settings.min_window_days, min(settings.max_window_days, window_days)
    )
    target_timestamp = int(time.time()) - (window_days * 86400)

    latest_block = await rpc.eth_block_number()
    rpc_calls = 1  # eth_blockNumber

    # Estimate start block based on ~2s block time
    estimated_blocks_back = window_days * 86400 // settings.base_block_time_seconds
    estimated_start = max(0, latest_block - estimated_blocks_back)

    # Binary search for the block closest to target_timestamp
    start_block, search_calls = await _binary_search_block_by_timestamp(
        rpc, target_timestamp, estimated_start, latest_block
    )
    rpc_calls += search_calls

    # Cap the block range if configured (for free RPC compatibility)
    if settings.max_scan_block_range > 0:
        max_start = latest_block - settings.max_scan_block_range
        if start_block < max_start:
            start_block = max_start

    return {
        "start_block": start_block,
        "end_block": latest_block,
        "window_days": window_days,
        "start_timestamp": target_timestamp,
        "rpc_calls_used": rpc_calls,
    }


async def _binary_search_block_by_timestamp(
    rpc: EvmRpcClient, target_ts: int, low: int, high: int
) -> tuple[int, int]:
    rpc_calls = 0
    for _ in range(20):  # max iterations safety
        if high - low <= 10:
            return low, rpc_calls
        mid = (low + high) // 2
        cached = mid in _block_ts_cache
        mid_ts = await rpc.get_block_timestamp(mid)
        if not cached:
            rpc_calls += 1
        if mid_ts < target_ts:
            low = mid
        else:
            high = mid
    return low, rpc_calls


base_rpc = EvmRpcClient(settings.base_rpc_url)
