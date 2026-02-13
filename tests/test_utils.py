from __future__ import annotations

import pytest

from app.utils.address import (
    normalize_address,
    pad_evm_address,
    validate_address,
    validate_evm_address,
    validate_solana_address,
)
from app.utils.params import extract_param


class TestValidateEvmAddress:
    def test_valid_lowercase(self):
        assert validate_evm_address("0x" + "a" * 40) is True

    def test_valid_mixed_case(self):
        assert validate_evm_address("0xABCdef1234567890abcdef1234567890ABCDEF12") is True

    def test_missing_0x(self):
        assert validate_evm_address("a" * 40) is False

    def test_too_short(self):
        assert validate_evm_address("0x" + "a" * 39) is False

    def test_too_long(self):
        assert validate_evm_address("0x" + "a" * 41) is False

    def test_invalid_chars(self):
        assert validate_evm_address("0x" + "g" * 40) is False

    def test_empty_string(self):
        assert validate_evm_address("") is False


class TestValidateSolanaAddress:
    def test_valid_address(self):
        # Typical Solana address length is 32-44 chars, base58
        assert validate_solana_address("11111111111111111111111111111111") is True

    def test_valid_long_address(self):
        assert validate_solana_address(
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        ) is True

    def test_too_short(self):
        assert validate_solana_address("abc") is False

    def test_invalid_base58_chars(self):
        # 0, O, I, l are not in base58
        assert validate_solana_address("0" * 32) is False
        assert validate_solana_address("O" * 32) is False
        assert validate_solana_address("I" * 32) is False
        assert validate_solana_address("l" * 32) is False

    def test_empty_string(self):
        assert validate_solana_address("") is False


class TestValidateAddress:
    def test_base_chain(self):
        assert validate_address("0x" + "a" * 40, "base") is True

    def test_solana_chain(self):
        assert validate_address("11111111111111111111111111111111", "solana") is True

    def test_unsupported_chain(self):
        assert validate_address("anything", "ethereum") is False


class TestNormalizeAddress:
    def test_evm_lowercased(self):
        addr = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"
        result = normalize_address(addr, "base")
        assert result == addr.lower()

    def test_solana_unchanged(self):
        addr = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        result = normalize_address(addr, "solana")
        assert result == addr


class TestExtractParam:
    def test_top_level_key(self):
        body = {"address": "0xabc"}
        assert extract_param(body, "address") == "0xabc"

    def test_alias_match(self):
        body = {"wallet": "0xabc"}
        assert extract_param(body, "address", aliases=["wallet", "addr"]) == "0xabc"

    def test_nested_body(self):
        """APIX402 nesting: body.body.address"""
        body = {"body": {"address": "0xabc"}}
        assert extract_param(body, "address") == "0xabc"

    def test_nested_body_with_alias(self):
        body = {"body": {"wallet": "0xabc"}}
        assert extract_param(body, "address", aliases=["wallet"]) == "0xabc"

    def test_query_fallback(self):
        body = {"query": "0xabc"}
        assert extract_param(body, "address") == "0xabc"

    def test_missing_returns_none(self):
        body = {"foo": "bar"}
        assert extract_param(body, "address") is None

    def test_top_level_takes_priority_over_nested(self):
        body = {"address": "top", "body": {"address": "nested"}}
        assert extract_param(body, "address") == "top"

    def test_empty_body(self):
        assert extract_param({}, "address") is None

    def test_flat_apix402_body(self):
        """Body already unwrapped by middleware."""
        body = {"address": "0xabc", "windowDays": 90}
        assert extract_param(body, "address") == "0xabc"
        assert extract_param(body, "windowDays", aliases=["window_days"]) == 90

    def test_window_days_alias(self):
        body = {"address": "0xabc", "window_days": 60}
        assert extract_param(body, "windowDays", aliases=["window_days", "days"]) == 60


class TestPadEvmAddress:
    def test_standard_address(self):
        addr = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
        padded = pad_evm_address(addr)
        assert padded.startswith("0x")
        assert len(padded) == 66  # 0x + 64 hex chars
        # Should be lowercased
        assert padded == padded.lower()

    def test_already_lowercase(self):
        addr = "0x" + "a" * 40
        padded = pad_evm_address(addr)
        assert padded == "0x" + "0" * 24 + "a" * 40

    def test_zero_padded_correctly(self):
        """Short address should be left-padded with zeros to 64 chars."""
        addr = "0x1"
        padded = pad_evm_address(addr)
        assert padded == "0x" + "0" * 63 + "1"

    def test_without_0x_prefix(self):
        """Address without 0x should still work (0x gets stripped and re-added)."""
        addr = "a" * 40
        padded = pad_evm_address(addr)
        assert padded == "0x" + "0" * 24 + "a" * 40


class TestAddressValidationBoundaries:
    def test_evm_exactly_42_chars(self):
        """0x + 40 hex chars is valid (exactly 42 chars total)."""
        assert validate_evm_address("0x" + "a" * 40) is True

    def test_evm_all_zeros(self):
        """Zero address is technically valid hex."""
        assert validate_evm_address("0x" + "0" * 40) is True

    def test_evm_mixed_valid_hex(self):
        assert validate_evm_address("0x1234567890abcdefABCDEF1234567890abcdef12") is True

    def test_evm_uppercase_0X_invalid(self):
        """Capital 0X should be invalid per regex."""
        assert validate_evm_address("0X" + "a" * 40) is False

    def test_solana_exactly_32_chars(self):
        """Minimum length Solana address."""
        assert validate_solana_address("1" * 32) is True

    def test_solana_exactly_44_chars(self):
        """Maximum length Solana address."""
        assert validate_solana_address("A" * 44) is True

    def test_solana_31_chars_too_short(self):
        assert validate_solana_address("A" * 31) is False

    def test_solana_45_chars_too_long(self):
        assert validate_solana_address("A" * 45) is False

    def test_solana_mixed_valid_base58(self):
        """All valid base58 chars: 1-9, A-H, J-N, P-Z, a-k, m-z."""
        assert validate_solana_address("123456789ABCDEFGHJKLMNPQRSTUVWXYZab") is True

    def test_validate_address_whitespace_not_stripped(self):
        """validate_address does not strip whitespace — caller should do that."""
        assert validate_address(" 0x" + "a" * 40, "base") is False


class TestNormalizeAddressBoundaries:
    def test_already_lowercase_evm(self):
        addr = "0x" + "a" * 40
        assert normalize_address(addr, "base") == addr

    def test_unknown_chain_returns_as_is(self):
        """Unknown chain returns address unchanged."""
        addr = "SomeAddress"
        assert normalize_address(addr, "ethereum") == addr


class TestExtractParamEdgeCases:
    def test_body_key_is_string_not_dict(self):
        """If body['body'] is not a dict, should not recurse into it."""
        body = {"body": "just_a_string"}
        assert extract_param(body, "address") is None

    def test_body_key_is_list(self):
        body = {"body": ["not", "a", "dict"]}
        assert extract_param(body, "address") is None

    def test_numeric_value_preserved(self):
        body = {"windowDays": 60}
        assert extract_param(body, "windowDays") == 60

    def test_boolean_value_preserved(self):
        body = {"verbose": True}
        assert extract_param(body, "verbose") is True

    def test_first_alias_wins_over_later(self):
        """If multiple aliases match, first one checked wins."""
        body = {"wallet": "wallet_val", "addr": "addr_val"}
        result = extract_param(body, "address", aliases=["wallet", "addr"])
        assert result == "wallet_val"

    def test_query_not_used_if_primary_found(self):
        """query fallback should NOT be used when primary key exists."""
        body = {"address": "real_address", "query": "query_value"}
        result = extract_param(body, "address")
        assert result == "real_address"

    def test_none_body_key_value(self):
        """If the matched key has None value, it should be returned as None."""
        body = {"address": None}
        result = extract_param(body, "address")
        assert result is None
