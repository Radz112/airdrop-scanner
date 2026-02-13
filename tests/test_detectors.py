from __future__ import annotations

import pytest

from app.detectors.base import DetectionResult
from app.detectors.program_id import ProgramIdMatchDetector, _tx_involves_program
from app.models.protocol import (
    ContractEntry,
    DetectionConfig,
    DetectionMode,
    Protocol,
    ProtocolCategory,
)
from app.services.scanner import (
    _append_empty_signal,
    _block_num_to_date,
    _build_tokened_signal,
    _build_tokenless_signal,
    _merge_result,
    _primary_mode,
    _unix_ts_to_date,
)


class TestMergeResult:
    def test_merge_empty_into_empty(self):
        target = DetectionResult()
        source = DetectionResult()
        _merge_result(target, source)
        assert target.interacted is False
        assert target.interaction_count == 0

    def test_merge_interacted_into_empty(self):
        target = DetectionResult()
        source = DetectionResult(
            interacted=True,
            interaction_count=5,
            signal_types=["swap"],
            first_seen="100",
            last_seen="200",
        )
        _merge_result(target, source)
        assert target.interacted is True
        assert target.interaction_count == 5
        assert "swap" in target.signal_types
        assert target.first_seen == "100"
        assert target.last_seen == "200"

    def test_merge_keeps_earliest_first_seen(self):
        target = DetectionResult(
            interacted=True, interaction_count=3,
            first_seen="200", last_seen="300",
        )
        source = DetectionResult(
            interacted=True, interaction_count=2,
            first_seen="100", last_seen="250",
        )
        _merge_result(target, source)
        assert target.interaction_count == 5
        assert target.first_seen == "100"
        assert target.last_seen == "300"

    def test_merge_keeps_latest_last_seen(self):
        target = DetectionResult(
            interacted=True, interaction_count=1,
            first_seen="100", last_seen="200",
        )
        source = DetectionResult(
            interacted=True, interaction_count=1,
            first_seen="150", last_seen="400",
        )
        _merge_result(target, source)
        assert target.last_seen == "400"

    def test_merge_accumulates_signal_types(self):
        target = DetectionResult(
            interacted=True, signal_types=["swap"],
        )
        source = DetectionResult(
            interacted=True, signal_types=["supply", "borrow"],
        )
        _merge_result(target, source)
        assert set(target.signal_types) == {"swap", "supply", "borrow"}


class TestTimestampConversion:
    def test_block_num_to_date(self):
        timestamps = {12345: 1707696000}  # 2024-02-12 00:00:00 UTC
        result = _block_num_to_date("12345", timestamps)
        assert result == "2024-02-12"

    def test_block_num_to_date_missing_timestamp(self):
        result = _block_num_to_date("12345", {})
        assert result is None

    def test_block_num_to_date_invalid_string(self):
        result = _block_num_to_date("not_a_number", {})
        assert result is None

    def test_unix_ts_to_date(self):
        result = _unix_ts_to_date("1707696000")  # 2024-02-12
        assert result == "2024-02-12"

    def test_unix_ts_to_date_invalid(self):
        result = _unix_ts_to_date("bad")
        assert result is None

    def test_unix_ts_to_date_none_like(self):
        result = _unix_ts_to_date("")
        assert result is None


def _contract(address, detection_config=None, **kwargs):
    return ContractEntry(
        address=address,
        label=kwargs.get("label", "test"),
        type=kwargs.get("type", "core"),
        detection_mode=kwargs.get("detection_mode", DetectionMode.PROGRAM_ID_MATCH),
        detection_config=detection_config or DetectionConfig(),
    )


class TestProgramIdMatch:
    def test_helius_format_match(self):
        """Helius enhanced tx with matching program ID."""
        contract = _contract("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")
        txs = [
            {
                "type": "SWAP",
                "timestamp": 1707696000,
                "instructions": [
                    {"programId": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"}
                ],
            },
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs)
        assert result.interacted is True
        assert result.interaction_count == 1
        assert "SWAP" in result.signal_types

    def test_no_match(self):
        contract = _contract("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")
        txs = [
            {
                "type": "TRANSFER",
                "instructions": [
                    {"programId": "SomeOtherProgram111111111111111111111"}
                ],
            },
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs)
        assert result.interacted is False

    def test_inner_instruction_match(self):
        contract = _contract("MATCHprog111111111111111111111111111")
        txs = [
            {
                "type": "UNKNOWN",
                "timestamp": 1707700000,
                "instructions": [
                    {
                        "programId": "OtherProg",
                        "innerInstructions": [
                            {"programId": "MATCHprog111111111111111111111111111"}
                        ],
                    }
                ],
            },
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs)
        assert result.interacted is True

    def test_discriminator_filtering(self):
        contract = _contract(
            "ProgWithDisc1111111111111111111111111",
            detection_config=DetectionConfig(
                instruction_discriminators=["abc123"],
            ),
        )
        # TX with matching program but wrong discriminator
        txs_no_match = [
            {
                "type": "UNKNOWN",
                "instructions": [
                    {"programId": "ProgWithDisc1111111111111111111111111", "data": "xyz999"}
                ],
            },
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs_no_match)
        assert result.interacted is False

        # TX with matching program and correct discriminator
        txs_match = [
            {
                "type": "STAKE",
                "timestamp": 1707700000,
                "instructions": [
                    {"programId": "ProgWithDisc1111111111111111111111111", "data": "abc123deadbeef"}
                ],
            },
        ]
        result = detector.detect_from_parsed_txs(contract, txs_match)
        assert result.interacted is True

    def test_timestamps_first_last(self):
        contract = _contract("TimeProg1111111111111111111111111111")
        txs = [
            {
                "type": "A",
                "timestamp": 1000,
                "instructions": [{"programId": "TimeProg1111111111111111111111111111"}],
            },
            {
                "type": "B",
                "timestamp": 3000,
                "instructions": [{"programId": "TimeProg1111111111111111111111111111"}],
            },
            {
                "type": "A",
                "timestamp": 2000,
                "instructions": [{"programId": "TimeProg1111111111111111111111111111"}],
            },
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs)
        assert result.first_seen == "1000"
        assert result.last_seen == "3000"
        assert result.interaction_count == 3


class TestTxInvolvesProgram:
    def test_account_data_match(self):
        tx = {
            "accountData": [{"account": "TargetProg"}],
            "instructions": [],
        }
        assert _tx_involves_program(tx, "TargetProg", set()) is True

    def test_raw_json_parsed_format(self):
        tx = {
            "instructions": [],
            "transaction": {
                "message": {
                    "accountKeys": [
                        {"pubkey": "TargetProg"},
                        {"pubkey": "OtherKey"},
                    ]
                }
            },
        }
        assert _tx_involves_program(tx, "TargetProg", set()) is True

    def test_no_match_anywhere(self):
        tx = {
            "instructions": [{"programId": "Other"}],
            "accountData": [],
        }
        assert _tx_involves_program(tx, "Target", set()) is False


class TestMergeResultEdgeCases:
    def test_merge_non_interacted_into_interacted(self):
        """Merging a non-interacted source should not change target."""
        target = DetectionResult(
            interacted=True, interaction_count=5,
            first_seen="100", last_seen="200",
            signal_types=["swap"],
        )
        source = DetectionResult(interacted=False)
        _merge_result(target, source)
        assert target.interacted is True
        assert target.interaction_count == 5
        assert target.first_seen == "100"
        assert target.last_seen == "200"
        assert target.signal_types == ["swap"]

    def test_merge_source_with_none_first_seen(self):
        """Source interacted but first_seen is None → target first_seen unchanged."""
        target = DetectionResult(
            interacted=True, interaction_count=2,
            first_seen="100", last_seen="200",
        )
        source = DetectionResult(
            interacted=True, interaction_count=1,
            first_seen=None, last_seen="300",
        )
        _merge_result(target, source)
        assert target.first_seen == "100"
        assert target.last_seen == "300"
        assert target.interaction_count == 3

    def test_merge_source_with_none_last_seen(self):
        """Source interacted but last_seen is None → target last_seen unchanged."""
        target = DetectionResult(
            interacted=True, interaction_count=2,
            first_seen="100", last_seen="200",
        )
        source = DetectionResult(
            interacted=True, interaction_count=1,
            first_seen="050", last_seen=None,  # 50 < 100 as integers
        )
        _merge_result(target, source)
        assert target.first_seen == "050"
        assert target.last_seen == "200"

    def test_merge_first_seen_uses_integer_comparison(self):
        """first_seen/last_seen are compared as integers (block numbers)."""
        target = DetectionResult(
            interacted=True, interaction_count=1,
            first_seen="100", last_seen="200",
        )
        source = DetectionResult(
            interacted=True, interaction_count=1,
            first_seen="99", last_seen=None,
        )
        _merge_result(target, source)
        # 99 < 100 as integers → source wins
        assert target.first_seen == "99"

    def test_merge_multiple_sources(self):
        """Merge 3 sources sequentially → accumulates correctly."""
        target = DetectionResult()
        sources = [
            DetectionResult(interacted=True, interaction_count=2, signal_types=["swap"],
                          first_seen="200", last_seen="300"),
            DetectionResult(interacted=True, interaction_count=3, signal_types=["supply"],
                          first_seen="100", last_seen="250"),
            DetectionResult(interacted=True, interaction_count=1, signal_types=["borrow"],
                          first_seen="150", last_seen="400"),
        ]
        for s in sources:
            _merge_result(target, s)
        assert target.interacted is True
        assert target.interaction_count == 6
        assert set(target.signal_types) == {"swap", "supply", "borrow"}
        assert target.first_seen == "100"
        assert target.last_seen == "400"

    def test_merge_duplicate_signal_types(self):
        """Merge extends signal_types without deduplication (caller handles it)."""
        target = DetectionResult(interacted=True, signal_types=["swap"])
        source = DetectionResult(interacted=True, signal_types=["swap"])
        _merge_result(target, source)
        assert target.signal_types == ["swap", "swap"]


class TestProgramIdMatchEdgeCases:
    def test_empty_transaction_list(self):
        contract = _contract("SomeProg111111111111111111111111111")
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, [])
        assert result.interacted is False
        assert result.interaction_count == 0
        assert result.signal_types == []

    def test_transactions_without_timestamps(self):
        """Transactions missing timestamp field → first/last_seen stays None."""
        contract = _contract("Prog111111111111111111111111111111111")
        txs = [
            {
                "type": "SWAP",
                "instructions": [{"programId": "Prog111111111111111111111111111111111"}],
                # No "timestamp" key
            },
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs)
        assert result.interacted is True
        assert result.interaction_count == 1
        assert result.first_seen is None
        assert result.last_seen is None

    def test_multiple_discriminators(self):
        """Contract with multiple valid discriminators."""
        contract = _contract(
            "ProgMultiDisc111111111111111111111111",
            detection_config=DetectionConfig(
                instruction_discriminators=["aaa", "bbb", "ccc"],
            ),
        )
        txs = [
            {
                "type": "A",
                "timestamp": 1000,
                "instructions": [{"programId": "ProgMultiDisc111111111111111111111111", "data": "bbbXXX"}],
            },
            {
                "type": "B",
                "timestamp": 2000,
                "instructions": [{"programId": "ProgMultiDisc111111111111111111111111", "data": "cccYYY"}],
            },
            {
                "type": "C",
                "timestamp": 3000,
                "instructions": [{"programId": "ProgMultiDisc111111111111111111111111", "data": "zzzNO"}],
            },
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs)
        assert result.interacted is True
        assert result.interaction_count == 2  # first two match, third doesn't
        assert set(result.signal_types) == {"A", "B"}

    def test_whitespace_in_address_stripped(self):
        """Contract address with whitespace should still match."""
        contract = _contract(" SpaceProg1111111111111111111111111 ")
        txs = [
            {
                "type": "SWAP",
                "timestamp": 1000,
                "instructions": [{"programId": "SpaceProg1111111111111111111111111"}],
            },
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs)
        assert result.interacted is True

    def test_same_tx_type_deduplicates_in_signal_types(self):
        """Multiple txs with same type → signal_types uses set."""
        contract = _contract("Dedup111111111111111111111111111111")
        txs = [
            {"type": "SWAP", "timestamp": 1000, "instructions": [{"programId": "Dedup111111111111111111111111111111"}]},
            {"type": "SWAP", "timestamp": 2000, "instructions": [{"programId": "Dedup111111111111111111111111111111"}]},
            {"type": "SWAP", "timestamp": 3000, "instructions": [{"programId": "Dedup111111111111111111111111111111"}]},
        ]
        detector = ProgramIdMatchDetector()
        result = detector.detect_from_parsed_txs(contract, txs)
        assert result.interaction_count == 3
        assert result.signal_types == ["SWAP"]  # deduplicated via set


class TestTxInvolvesProgramEdgeCases:
    def test_empty_tx_dict(self):
        assert _tx_involves_program({}, "Target", set()) is False

    def test_raw_format_string_account_keys(self):
        """Raw format where accountKeys are plain strings, not dicts."""
        tx = {
            "instructions": [],
            "transaction": {
                "message": {
                    "accountKeys": ["TargetProg", "OtherKey"]
                }
            },
        }
        assert _tx_involves_program(tx, "TargetProg", set()) is True

    def test_discriminator_only_checks_top_level_instructions(self):
        """Discriminators are only checked for top-level instructions, not inner."""
        tx = {
            "instructions": [
                {
                    "programId": "OtherProg",
                    "innerInstructions": [
                        {"programId": "TargetProg", "data": "abc123xyz"}
                    ],
                }
            ],
        }
        # Inner instruction match bypasses discriminator check
        assert _tx_involves_program(tx, "TargetProg", {"abc123"}) is True

    def test_no_instructions_key(self):
        """Transaction with no instructions key at all."""
        tx = {"accountData": [{"account": "SomeProg"}]}
        assert _tx_involves_program(tx, "SomeProg", set()) is True

    def test_empty_discriminator_set_matches_all(self):
        """Empty discriminator set means no filtering."""
        tx = {
            "instructions": [{"programId": "Target", "data": "anything"}],
        }
        assert _tx_involves_program(tx, "Target", set()) is True


class TestTimestampConversionEdgeCases:
    def test_block_num_zero_timestamp(self):
        """Block with timestamp 0 should return None (falsy)."""
        result = _block_num_to_date("1", {1: 0})
        assert result is None

    def test_unix_ts_zero(self):
        """Unix timestamp 0 = epoch start."""
        result = _unix_ts_to_date("0")
        # 0 is falsy in `if ts:` — so this actually returns None
        # Wait, let me check: `ts = int("0")` → 0, then
        # `return datetime.fromtimestamp(0, ...)` — there's no `if ts:` check in _unix_ts_to_date
        assert result == "1970-01-01"

    def test_block_num_negative(self):
        """Negative block number — should handle gracefully."""
        result = _block_num_to_date("-1", {-1: 1707696000})
        assert result == "2024-02-12"

    def test_unix_ts_very_large(self):
        """Very large timestamp — year 2100."""
        result = _unix_ts_to_date("4102444800")
        assert result == "2100-01-01"

    def test_block_num_float_string(self):
        """Float string should fail int conversion → None."""
        result = _block_num_to_date("123.45", {})
        assert result is None


def _make_protocol(
    id: str = "test",
    name: str = "Test",
    chain: str = "base",
    category: str = "dex",
    has_token: bool = False,
    token_symbol: str | None = None,
    protocol_weight: float = 1.0,
    contracts: list | None = None,
) -> Protocol:
    return Protocol(
        id=id,
        name=name,
        chain=chain,
        category=ProtocolCategory(category),
        has_token=has_token,
        token_symbol=token_symbol,
        protocol_weight=protocol_weight,
        contracts=contracts or [],
    )


class TestPrimaryMode:
    def test_protocol_with_contracts(self):
        c = _contract("0xabc", detection_mode=DetectionMode.EVENT_TOPIC)
        p = _make_protocol(contracts=[c])
        assert _primary_mode(p) == "event_topic"

    def test_protocol_no_contracts(self):
        p = _make_protocol(contracts=[])
        assert _primary_mode(p) == "unknown"

    def test_uses_first_contract_mode(self):
        c1 = _contract("0xabc", detection_mode=DetectionMode.TX_TO_CONTRACT)
        c2 = _contract("0xdef", detection_mode=DetectionMode.EVENT_TOPIC)
        p = _make_protocol(contracts=[c1, c2])
        assert _primary_mode(p) == "tx_to_contract"


class TestBuildTokenedSignal:
    def test_interacted_with_token(self):
        p = _make_protocol(
            id="uniswap", name="Uniswap", category="dex",
            has_token=True, token_symbol="UNI",
        )
        result = DetectionResult(interacted=True, interaction_count=5)
        signal = _build_tokened_signal(p, result)
        assert signal.protocol_id == "uniswap"
        assert signal.protocol_name == "Uniswap"
        assert signal.category == "dex"
        assert signal.token_symbol == "UNI"
        assert signal.interacted is True
        assert "$UNI" in signal.note

    def test_interacted_no_token_symbol(self):
        """has_token=True but token_symbol=None → empty note."""
        p = _make_protocol(has_token=True, token_symbol=None)
        result = DetectionResult(interacted=True)
        signal = _build_tokened_signal(p, result)
        assert signal.note == ""
        assert signal.token_symbol == ""

    def test_not_interacted_no_note(self):
        """Not interacted → note is always empty."""
        p = _make_protocol(has_token=True, token_symbol="TKN")
        result = DetectionResult(interacted=False)
        signal = _build_tokened_signal(p, result)
        assert signal.interacted is False
        assert signal.note == ""


class TestBuildTokenlessSignal:
    def test_interacted_signal(self):
        c = _contract("0xabc", detection_mode=DetectionMode.EVENT_TOPIC)
        p = _make_protocol(
            id="morpho", name="Morpho", category="lending",
            protocol_weight=1.2, contracts=[c],
        )
        result = DetectionResult(
            interacted=True, interaction_count=10,
            signal_types=["supply", "borrow", "supply"],
            first_seen="12345", last_seen="67890",
        )
        signal = _build_tokenless_signal(p, result)
        assert signal.protocol_id == "morpho"
        assert signal.protocol_weight == 1.2
        assert signal.interacted is True
        assert signal.interaction_count == 10
        assert signal.first_seen == "12345"
        assert signal.last_seen == "67890"
        assert signal.signal_strength == "none"  # Scored later
        assert signal.detection_mode == "event_topic"
        # signal_types are deduplicated via set
        assert set(signal.signal_types) == {"supply", "borrow"}

    def test_empty_result(self):
        p = _make_protocol(id="p1", contracts=[])
        result = DetectionResult()
        signal = _build_tokenless_signal(p, result)
        assert signal.interacted is False
        assert signal.interaction_count == 0
        assert signal.signal_types == []
        assert signal.first_seen is None
        assert signal.last_seen is None
        assert signal.detection_mode == "unknown"


class TestAppendEmptySignal:
    def test_tokened_protocol_appends_tokened(self):
        p = _make_protocol(has_token=True, token_symbol="TKN")
        tokenless, tokened = [], []
        _append_empty_signal(p, tokenless, tokened)
        assert len(tokenless) == 0
        assert len(tokened) == 1
        assert tokened[0].interacted is False
        assert tokened[0].note == ""

    def test_tokenless_protocol_appends_tokenless(self):
        c = _contract("0xabc", detection_mode=DetectionMode.TX_TO_CONTRACT)
        p = _make_protocol(has_token=False, contracts=[c])
        tokenless, tokened = [], []
        _append_empty_signal(p, tokenless, tokened)
        assert len(tokenless) == 1
        assert len(tokened) == 0
        assert tokenless[0].interacted is False
        assert tokenless[0].interaction_count == 0
        assert tokenless[0].detection_mode == "tx_to_contract"

    def test_multiple_appends_accumulate(self):
        p1 = _make_protocol(id="p1", has_token=False, contracts=[])
        p2 = _make_protocol(id="p2", has_token=True, token_symbol="TK")
        p3 = _make_protocol(id="p3", has_token=False, contracts=[])
        tokenless, tokened = [], []
        _append_empty_signal(p1, tokenless, tokened)
        _append_empty_signal(p2, tokenless, tokened)
        _append_empty_signal(p3, tokenless, tokened)
        assert len(tokenless) == 2
        assert len(tokened) == 1
