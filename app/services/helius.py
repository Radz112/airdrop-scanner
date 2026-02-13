from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("helius")


class HeliusClient:
    def __init__(self):
        self._api_key = settings.helius_api_key
        self._base_url = settings.helius_base_url
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path}?api-key={self._api_key}"

    def _rpc_url(self) -> str:
        return f"https://mainnet.helius-rpc.com/?api-key={self._api_key}"

    async def get_signatures_for_address(
        self,
        address: str,
        limit: int = 1000,
        before: str | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if before:
            params["before"] = before

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [address, params],
        }
        client = self._get_client()
        resp = await client.post(self._rpc_url(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Helius RPC error: {data['error']}")
        return data.get("result", [])

    async def parse_transactions(
        self, signatures: list[str]
    ) -> list[dict]:
        if not signatures:
            return []

        url = self._url("v0/transactions")
        client = self._get_client()
        resp = await client.post(
            url,
            json={"transactions": signatures},
        )
        resp.raise_for_status()
        return resp.json()


class SolanaRpcClient:
    def __init__(self, rpc_url: str):
        self._url = rpc_url
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def get_signatures_for_address(
        self,
        address: str,
        limit: int = 1000,
        before: str | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if before:
            params["before"] = before

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [address, params],
        }
        client = self._get_client()
        resp = await client.post(self._url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Solana RPC error: {data['error']}")
        return data.get("result", [])

    async def get_account_info(self, address: str) -> dict | None:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [address, {"encoding": "jsonParsed"}],
        }
        client = self._get_client()
        resp = await client.post(self._url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", {}).get("value")

    async def get_transaction(self, signature: str) -> dict | None:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
            ],
        }
        client = self._get_client()
        resp = await client.post(self._url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result")


helius_client = HeliusClient()
solana_rpc = SolanaRpcClient(settings.solana_rpc_url)
