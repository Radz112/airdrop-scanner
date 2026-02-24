from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from app.config import settings
from app.models.response import ScanResponse, SkippedProtocol
from app.services.cache import scan_cache
from app.services.helius import solana_rpc
from app.services.protocol_db import protocol_db
from app.services.rpc import base_rpc
from app.services.scanner import scan_wallet
from app.services.scoring import (
    build_summary,
    calculate_strength,
    generate_next_actions,
)
from app.utils.address import normalize_address, validate_address
from app.utils.errors import error_response
from app.utils.params import extract_param

logger = logging.getLogger("routes.airdrop")

router = APIRouter(prefix="/v1/airdrop-exposure")


def _validate_chain(chain: str) -> str | None:
    if chain not in settings.supported_chains:
        return f"Unsupported chain: '{chain}'. Supported: {settings.supported_chains}"
    return None


@router.get("/{chain}")
async def airdrop_exposure_info(chain: str):
    """Registration/info endpoint for APIX402."""
    err = _validate_chain(chain)
    if err:
        return error_response(400, err)

    return {
        "endpoint": f"/v1/airdrop-exposure/{chain}",
        "method": "POST",
        "description": (
            f"Scan a wallet for airdrop likelihood based on "
            f"protocol interactions on {chain.title()}"
        ),
        "chain": chain,
        "parameters": {
            "address": "Wallet address (required)",
            "windowDays": "Scan window in days (optional, default 90, range 30-180)",
        },
        "pricing": "x402 micropayment per request",
        "disclaimer": (
            "Results reflect interaction patterns only. Actual airdrop eligibility "
            "is determined solely by each protocol."
        ),
    }


@router.post("/{chain}")
async def airdrop_exposure_scan(chain: str, request: Request):
    """Paid scan endpoint — scans wallet for airdrop exposure."""
    err = _validate_chain(chain)
    if err:
        return error_response(400, err)

    body = getattr(request.state, "parsed_body", {})
    client_ip = request.client.host if request.client else "unknown"
    logger.info(f"POST /{chain} from {client_ip}, parsed_body={body}")

    address = extract_param(body, "address", aliases=["wallet", "addr", chain])
    if not address or not isinstance(address, str):
        logger.warning(f"400 Missing address, received_body={body}")
        return error_response(
            400, "Missing required parameter: 'address'", received_body=body
        )

    address = address.strip()
    if not validate_address(address, chain):
        logger.warning(f"400 Invalid address: '{address}', chain={chain}, received_body={body}")
        return error_response(
            400,
            f"Invalid {chain} address: '{address}'",
            received_body=body,
        )

    address = normalize_address(address, chain)

    raw_window = extract_param(body, "windowDays", aliases=["window_days", "days"])
    window_days = settings.default_window_days
    if raw_window is not None:
        try:
            window_days = int(raw_window)
            window_days = max(settings.min_window_days, min(settings.max_window_days, window_days))
        except (ValueError, TypeError):
            window_days = settings.default_window_days

    logger.info(f"Resolved params: address={address}, windowDays={window_days}")

    cache_key = f"{chain}:{address}:{window_days}"
    cached = scan_cache.get(cache_key)
    if cached:
        logger.info(f"Cache hit for {cache_key}")
        return cached

    protocols = protocol_db.get_by_chain(chain)
    if not protocols:
        logger.warning(f"503 No protocols for chain '{chain}'")
        return error_response(
            503,
            f"No protocols loaded for chain '{chain}'. Database may be empty.",
        )

    wallet_type = await _detect_wallet_type(address, chain)
    wallet_note = None
    if wallet_type == "contract":
        wallet_note = (
            "This appears to be a smart contract wallet. Some interactions "
            "may be attributed to the contract deployer or implementation, "
            "not this address directly."
        )
    elif wallet_type == "unknown":
        wallet_note = (
            "Wallet type detection failed (RPC error). Results may still be valid "
            "but contract vs EOA distinction could not be determined."
        )

    tokenless_signals, tokened_signals, completeness, skipped_ids = await scan_wallet(
        address, chain, protocols, window_days
    )

    for signal in tokenless_signals:
        signal.signal_strength = calculate_strength(
            count=signal.interaction_count,
            types=signal.signal_types,
            first_seen=signal.first_seen,
            last_seen=signal.last_seen,
            protocol_weight=signal.protocol_weight,
        )

    summary = build_summary(tokenless_signals, tokened_signals)
    next_actions = generate_next_actions(summary, tokenless_signals, chain)

    partial_scan_note = None
    if completeness == "partial":
        partial_scan_note = (
            "Scan was truncated due to RPC budget or time limits. "
            "Some protocols may not have been fully scanned."
        )
    elif completeness == "error":
        partial_scan_note = (
            "Scan failed due to an RPC error when computing the block range. "
            "No protocols were scanned. Try again later."
        )

    skipped_protocols = [
        SkippedProtocol(
            protocol_id=pid,
            reason="Scan truncated due to budget limits"
            if completeness == "partial"
            else "Scan failed due to RPC error",
        )
        for pid in skipped_ids
    ]

    response = ScanResponse(
        address=address,
        chain=chain,
        scan_timestamp=datetime.now(timezone.utc).isoformat(),
        scan_completeness=completeness,
        scan_window_days=window_days,
        wallet_type=wallet_type,
        tokenless_signals=tokenless_signals,
        tokened_signals=tokened_signals,
        summary=summary,
        next_actions=next_actions,
        skipped_protocols=skipped_protocols,
        partial_scan_note=partial_scan_note,
        wallet_note=wallet_note,
    )

    result = response.model_dump(by_alias=True)

    scan_cache.set(cache_key, result)
    logger.info(
        f"Scan complete for {cache_key}: "
        f"tokenless_signals={len(tokenless_signals)}, "
        f"tokened_signals={len(tokened_signals)}, "
        f"completeness={completeness}"
    )

    return result


async def _detect_wallet_type(address: str, chain: str) -> str:
    try:
        if chain == "solana":
            account_info = await solana_rpc.get_account_info(address)
            if account_info is None:
                return "eoa"
            return "contract" if account_info.get("executable") else "eoa"
        else:
            code = await base_rpc.eth_get_code(address)
            return "contract" if code and code not in ("0x", "0x0") else "eoa"
    except Exception as e:
        logger.warning(f"Wallet type detection failed for {address}: {e}")
        return "unknown"
