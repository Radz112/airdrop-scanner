from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.config import settings
from app.detectors.base import DetectionResult
from app.detectors.event_topic import EventTopicDetector
from app.detectors.program_id import ProgramIdMatchDetector
from app.detectors.transfer_to import TransferToContractDetector
from app.detectors.tx_to import TxToContractDetector
from app.models.protocol import DetectionMode, Protocol
from app.models.response import TokenedSignal, TokenlessSignal
from app.services.helius import helius_client, solana_rpc
from app.services.rpc import base_rpc, compute_scan_window

logger = logging.getLogger("scanner")

_evm_detectors: dict | None = None


def _get_evm_detector(mode: DetectionMode):
    global _evm_detectors
    if _evm_detectors is None:
        _evm_detectors = {
            DetectionMode.EVENT_TOPIC: EventTopicDetector(base_rpc),
            DetectionMode.TRANSFER_TO_CONTRACT: TransferToContractDetector(base_rpc),
            DetectionMode.TX_TO_CONTRACT: TxToContractDetector(base_rpc),
        }
    return _evm_detectors.get(mode)


async def _scan_evm_protocol(
    user_address: str,
    protocol: Protocol,
    from_block: int,
    to_block: int,
    rpc_budget: int,
) -> tuple[DetectionResult, int]:
    merged = DetectionResult()
    total_rpc = 0

    for contract in protocol.contracts:
        if total_rpc >= rpc_budget:
            break

        remaining = rpc_budget - total_rpc

        if contract.detection_mode == DetectionMode.HYBRID:
            sub_results = await _run_hybrid_evm(
                user_address, contract, from_block, to_block, remaining
            )
            for sub_result, sub_calls in sub_results:
                total_rpc += sub_calls
                _merge_result(merged, sub_result)
            continue

        if contract.detection_mode == DetectionMode.PROGRAM_ID_MATCH:
            continue  # Solana-only mode, skip on EVM

        detector = _get_evm_detector(contract.detection_mode)
        if not detector:
            continue

        result = await detector.detect(
            user_address, contract, from_block, to_block, remaining
        )
        total_rpc += result.rpc_calls_used
        _merge_result(merged, result)

    return merged, total_rpc


async def _run_hybrid_evm(user_address, contract, from_block, to_block, budget):
    results = []
    config = contract.detection_config
    if not config or not config.sub_detectors:
        return results

    used = 0
    for sub in config.sub_detectors:
        if used >= budget:
            break
        mode_str = sub.get("mode")
        try:
            mode = DetectionMode(mode_str)
        except ValueError:
            continue
        detector = _get_evm_detector(mode)
        if not detector:
            continue
        result = await detector.detect(
            user_address, contract, from_block, to_block, budget - used
        )
        used += result.rpc_calls_used
        results.append((result, result.rpc_calls_used))

    return results


async def _fetch_solana_signatures(user_address: str) -> list[dict]:
    """Raises on RPC failure so the caller can surface it as completeness='error'."""
    if helius_client.available:
        return await helius_client.get_signatures_for_address(
            user_address, limit=settings.max_solana_signatures
        )
    return await solana_rpc.get_signatures_for_address(
        user_address, limit=settings.max_solana_signatures
    )


async def _parse_solana_transactions(signatures: list[str]) -> tuple[list[dict], int]:
    """Returns (parsed_txs, failure_count). Falls back to raw RPC if Helius fails."""
    if not signatures:
        return [], 0

    if helius_client.available:
        try:
            all_parsed: list[dict] = []
            batch_size = settings.max_solana_parse_batch
            for i in range(0, len(signatures), batch_size):
                batch = signatures[i : i + batch_size]
                parsed = await helius_client.parse_transactions(batch)
                all_parsed.extend(parsed)
            return all_parsed, 0
        except Exception as e:
            logger.warning(f"Helius parse failed, falling back to raw RPC: {e}")

    # Fallback: fetch individual transactions via raw RPC
    parsed: list[dict] = []
    failures = 0
    for sig in signatures[: settings.max_solana_parse_batch]:
        try:
            tx = await solana_rpc.get_transaction(sig)
            if tx:
                parsed.append(tx)
        except Exception as e:
            failures += 1
            logger.warning(f"Failed to fetch tx {sig[:16]}...: {e}")
    return parsed, failures


async def _scan_solana_protocols(
    user_address: str,
    protocols: list[Protocol],
    start_time: float,
) -> tuple[list[TokenlessSignal], list[TokenedSignal], str, list[str]]:
    tokenless_signals: list[TokenlessSignal] = []
    tokened_signals: list[TokenedSignal] = []
    completeness = "full"
    skipped: list[str] = []

    try:
        sig_results = await _fetch_solana_signatures(user_address)
    except Exception as e:
        logger.error(f"Failed to fetch Solana signatures: {e}")
        return [], [], "error", [p.id for p in protocols]

    sig_ids = [s.get("signature") for s in sig_results if s.get("signature")]

    if not sig_ids:
        logger.info(f"No Solana signatures found for {user_address}")
        for protocol in protocols:
            _append_empty_signal(protocol, tokenless_signals, tokened_signals)
        return tokenless_signals, tokened_signals, completeness, skipped

    parsed_txs, parse_failures = await _parse_solana_transactions(sig_ids)
    logger.info(f"Parsed {len(parsed_txs)} Solana transactions ({parse_failures} failures)")
    if parse_failures > 0 and parse_failures >= len(sig_ids) * 0.5:
        completeness = "partial"

    detector = ProgramIdMatchDetector()

    for i, protocol in enumerate(protocols):
        elapsed = time.monotonic() - start_time
        if elapsed >= settings.max_scan_seconds:
            completeness = "partial"
            skipped = [p.id for p in protocols[i:]]
            break

        result = DetectionResult()
        for contract in protocol.contracts:
            sub = detector.detect_from_parsed_txs(contract, parsed_txs)
            _merge_result(result, sub)

        if protocol.has_token:
            tokened_signals.append(_build_tokened_signal(protocol, result))
        else:
            tokenless_signals.append(_build_tokenless_signal(protocol, result))

    # Convert Solana Unix timestamps to ISO dates
    for s in tokenless_signals:
        if s.first_seen:
            s.first_seen = _unix_ts_to_date(s.first_seen)
        if s.last_seen:
            s.last_seen = _unix_ts_to_date(s.last_seen)

    return tokenless_signals, tokened_signals, completeness, skipped


def _safe_int(val: str | None) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _merge_result(target: DetectionResult, source: DetectionResult) -> None:
    if source.interacted:
        target.interacted = True
        target.interaction_count += source.interaction_count
        target.signal_types.extend(source.signal_types)
        if source.first_seen:
            src_first = _safe_int(source.first_seen)
            tgt_first = _safe_int(target.first_seen)
            if src_first is not None and (tgt_first is None or src_first < tgt_first):
                target.first_seen = source.first_seen
        if source.last_seen:
            src_last = _safe_int(source.last_seen)
            tgt_last = _safe_int(target.last_seen)
            if src_last is not None and (tgt_last is None or src_last > tgt_last):
                target.last_seen = source.last_seen


def _primary_mode(protocol: Protocol) -> str:
    return protocol.contracts[0].detection_mode.value if protocol.contracts else "unknown"


def _build_tokened_signal(protocol: Protocol, result: DetectionResult) -> TokenedSignal:
    return TokenedSignal(
        protocol_id=protocol.id,
        protocol_name=protocol.name,
        category=protocol.category.value,
        token_symbol=protocol.token_symbol or "",
        interacted=result.interacted,
        note=(
            f"Already has token (${protocol.token_symbol}) "
            "— included for completeness"
            if result.interacted and protocol.token_symbol
            else ""
        ),
    )


def _build_tokenless_signal(protocol: Protocol, result: DetectionResult) -> TokenlessSignal:
    return TokenlessSignal(
        protocol_id=protocol.id,
        protocol_name=protocol.name,
        category=protocol.category.value,
        protocol_weight=protocol.protocol_weight,
        interacted=result.interacted,
        first_seen=result.first_seen,
        last_seen=result.last_seen,
        interaction_count=result.interaction_count,
        signal_types=list(set(result.signal_types)),
        signal_strength="none",  # Scored later by scoring service
        detection_mode=_primary_mode(protocol),
    )


def _append_empty_signal(
    protocol: Protocol,
    tokenless: list[TokenlessSignal],
    tokened: list[TokenedSignal],
) -> None:
    empty = DetectionResult()
    if protocol.has_token:
        tokened.append(_build_tokened_signal(protocol, empty))
    else:
        tokenless.append(_build_tokenless_signal(protocol, empty))


def _block_num_to_date(block_num_str: str, timestamps: dict[int, int]) -> str | None:
    try:
        bn = int(block_num_str)
        ts = timestamps.get(bn)
        if ts:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    return None


def _unix_ts_to_date(ts_str: str) -> str | None:
    try:
        ts = int(ts_str)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    return None


async def scan_wallet(
    address: str,
    chain: str,
    protocols: list[Protocol],
    window_days: int,
) -> tuple[list[TokenlessSignal], list[TokenedSignal], str, list[str]]:
    """Returns (tokenless_signals, tokened_signals, completeness, skipped_protocol_ids)."""
    start_time = time.monotonic()

    if chain == "solana":
        return await _scan_solana_protocols(address, protocols, start_time)

    # Compute block range via binary search
    try:
        window = await compute_scan_window(base_rpc, window_days)
        from_block = window["start_block"]
        to_block = window["end_block"]
        rpc_used = window["rpc_calls_used"]
    except Exception as e:
        logger.error(f"Failed to compute scan window: {e}")
        return [], [], "error", [p.id for p in protocols]

    tokenless_signals: list[TokenlessSignal] = []
    tokened_signals: list[TokenedSignal] = []
    completeness = "full"
    skipped: list[str] = []

    for i, protocol in enumerate(protocols):
        elapsed = time.monotonic() - start_time
        if elapsed >= settings.max_scan_seconds:
            logger.warning(f"Wall-clock budget exceeded at {elapsed:.1f}s")
            completeness = "partial"
            skipped = [p.id for p in protocols[i:]]
            break
        if rpc_used >= settings.max_rpc_calls_per_scan:
            logger.warning(f"RPC budget exceeded at {rpc_used} calls")
            completeness = "partial"
            skipped = [p.id for p in protocols[i:]]
            break

        remaining_rpc = settings.max_rpc_calls_per_scan - rpc_used

        # Tokened: light scan (cap at 3 RPC calls), tokenless: full budget
        budget = min(remaining_rpc, 3) if protocol.has_token else remaining_rpc
        result, calls = await _scan_evm_protocol(
            address, protocol, from_block, to_block, budget
        )
        rpc_used += calls

        if protocol.has_token:
            tokened_signals.append(_build_tokened_signal(protocol, result))
        else:
            tokenless_signals.append(_build_tokenless_signal(protocol, result))

    # Convert EVM block numbers to ISO dates for scoring
    block_numbers: set[int] = set()
    for s in tokenless_signals:
        if s.first_seen:
            try:
                block_numbers.add(int(s.first_seen))
            except ValueError:
                pass
        if s.last_seen:
            try:
                block_numbers.add(int(s.last_seen))
            except ValueError:
                pass

    if block_numbers:
        timestamps = await base_rpc.batch_get_block_timestamps(block_numbers)
        for s in tokenless_signals:
            if s.first_seen:
                s.first_seen = _block_num_to_date(s.first_seen, timestamps)
            if s.last_seen:
                s.last_seen = _block_num_to_date(s.last_seen, timestamps)

    logger.info(
        f"Scan complete: {rpc_used} RPC calls, "
        f"{time.monotonic() - start_time:.1f}s, "
        f"completeness={completeness}"
    )

    return tokenless_signals, tokened_signals, completeness, skipped
