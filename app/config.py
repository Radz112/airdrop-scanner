from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # RPC endpoints
    base_rpc_url: str = "https://mainnet.base.org"
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"

    # Helius (Solana enhanced API)
    helius_api_key: str = ""
    helius_base_url: str = "https://api.helius.xyz"

    # Cache
    cache_ttl_seconds: int = 3600

    # Scan budgets — EVM
    max_rpc_calls_per_scan: int = 150
    max_scan_seconds: int = 15

    # Scan budgets — Solana
    max_solana_signatures: int = 1000
    max_solana_parse_batch: int = 100

    # Scan window defaults
    default_window_days: int = 90
    min_window_days: int = 30
    max_window_days: int = 180

    # Base chain block time (~2 seconds)
    base_block_time_seconds: int = 2

    # Max block range per eth_getLogs call (Alchemy limits to ~2k on Base)
    max_log_block_range: int = 2000

    # Max total block range for scan window (0 = unlimited, use for free RPC testing)
    max_scan_block_range: int = 0

    # Payment
    pay_to_address_base: str = ""
    pay_to_address_solana: str = ""

    # Server
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # Supported chains
    supported_chains: list[str] = ["base", "solana"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
