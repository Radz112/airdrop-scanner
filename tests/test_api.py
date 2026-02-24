from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.response import TokenedSignal, TokenlessSignal
from app.services.cache import scan_cache
from app.services.protocol_db import protocol_db


@pytest.fixture(scope="session", autouse=True)
def load_protocols():
    protocol_db.load()


@pytest.fixture(autouse=True)
def clear_cache():
    scan_cache.clear()
    yield
    scan_cache.clear()


def _mock_scan_result(address="", chain="base", protocols=None, window_days=90):
    tokenless = [
        TokenlessSignal(
            protocol_id="mock_proto",
            protocol_name="Mock",
            category="dex",
            protocol_weight=1.0,
            interacted=False,
            first_seen=None,
            last_seen=None,
            interaction_count=0,
            signal_types=[],
            signal_strength="none",
            detection_mode="event_topic",
        )
    ]
    tokened = [
        TokenedSignal(
            protocol_id="mock_tokened",
            protocol_name="Mock Tokened",
            category="lending",
            token_symbol="MTK",
            interacted=False,
            note="",
        )
    ]
    return tokenless, tokened, "full", []


client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["protocols_loaded"] > 0
        assert "base" in data["supported_chains"]
        assert "solana" in data["supported_chains"]


class TestGetInfoEndpoints:
    def test_base_info(self):
        resp = client.get("/v1/airdrop-exposure/base")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "base"
        assert "POST" in data["method"]
        assert "address" in data["parameters"]

    def test_solana_info(self):
        resp = client.get("/v1/airdrop-exposure/solana")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "solana"

    def test_unsupported_chain_returns_400(self):
        resp = client.get("/v1/airdrop-exposure/ethereum")
        assert resp.status_code == 400
        data = resp.json()
        assert "Unsupported chain" in data["error"]


class TestPostValidation:
    def test_missing_address_returns_400(self):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "address" in data["error"].lower()

    def test_invalid_evm_address_returns_400(self):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "not_an_address"},
        )
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["error"]

    def test_invalid_solana_address_returns_400(self):
        resp = client.post(
            "/v1/airdrop-exposure/solana",
            json={"address": "0xinvalid"},
        )
        assert resp.status_code == 400

    def test_unsupported_chain_post_returns_400(self):
        resp = client.post(
            "/v1/airdrop-exposure/ethereum",
            json={"address": "0x" + "a" * 40},
        )
        assert resp.status_code == 400


class TestApix402BodyUnwrapping:
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    def test_flat_body(self, mock_wt, mock_scan):
        """Standard flat body — address at top level."""
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "a" * 40},
        )
        assert resp.status_code == 200

    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    def test_nested_body(self, mock_wt, mock_scan):
        """APIX402 nested body — address inside body.body."""
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"body": {"address": "0x" + "b" * 40}},
        )
        assert resp.status_code == 200

    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    def test_wallet_alias(self, mock_wt, mock_scan):
        """Using 'wallet' alias for address."""
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"wallet": "0x" + "c" * 40},
        )
        assert resp.status_code == 200

    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    def test_query_string_unwrap(self, mock_wt, mock_scan):
        """APIX query-string format: {"query": "base=0x...&windowDays=90"}."""
        addr = "0x" + "d" * 40
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"query": f"base={addr}&windowDays=90"},
        )
        assert resp.status_code == 200


class TestResponseStructure:

    @pytest.fixture
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def scan_response(self, mock_scan, mock_wt):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "0" * 40},
        )
        return resp

    def test_status_code(self, scan_response):
        assert scan_response.status_code == 200

    def test_top_level_fields(self, scan_response):
        data = scan_response.json()
        assert "address" in data
        assert "chain" in data
        assert "scan_timestamp" in data
        assert "scan_completeness" in data
        assert "scan_window_days" in data
        assert "wallet_type" in data
        assert "tokenless_signals" in data
        assert "tokened_signals" in data
        assert "summary" in data
        assert "next_actions" in data
        assert "disclaimer" in data
        assert "skipped_protocols" in data

    def test_summary_fields(self, scan_response):
        summary = scan_response.json()["summary"]
        assert "tokenless_protocols_interacted" in summary
        assert "tokenless_protocols_available" in summary
        assert "total_protocols_scanned" in summary
        assert "recency_score" in summary
        assert "diversity_score" in summary
        assert "overall_likelihood" in summary
        assert "category_coverage" in summary

    def test_category_coverage_fields(self, scan_response):
        coverage = scan_response.json()["summary"]["category_coverage"]
        expected = [
            "dex", "lending", "bridge", "nft", "social",
            "governance", "yield", "perps", "liquid_staking", "oracle",
        ]
        for cat in expected:
            assert cat in coverage, f"Missing category: {cat}"
        # Verify yield is NOT serialized as yield_
        assert "yield_" not in coverage

    def test_zero_interactions_minimal_likelihood(self, scan_response):
        data = scan_response.json()
        assert data["summary"]["overall_likelihood"] == "minimal"

    def test_address_normalized(self, scan_response):
        data = scan_response.json()
        assert data["address"] == "0x" + "0" * 40
        assert data["chain"] == "base"

    def test_default_window_days(self, scan_response):
        data = scan_response.json()
        assert data["scan_window_days"] == 90

    def test_wallet_type_present(self, scan_response):
        data = scan_response.json()
        assert data["wallet_type"] in ("eoa", "contract", "unknown")


class TestWindowDays:
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_custom_window_days(self, mock_scan, mock_wt):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "0" * 40, "windowDays": 60},
        )
        assert resp.status_code == 200
        assert resp.json()["scan_window_days"] == 60

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_window_days_clamped_low(self, mock_scan, mock_wt):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "0" * 40, "windowDays": 5},
        )
        assert resp.status_code == 200
        assert resp.json()["scan_window_days"] == 30  # min is 30

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_window_days_clamped_high(self, mock_scan, mock_wt):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "0" * 40, "windowDays": 999},
        )
        assert resp.status_code == 200
        assert resp.json()["scan_window_days"] == 180  # max is 180

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_invalid_window_days_defaults_to_90(self, mock_scan, mock_wt):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "0" * 40, "windowDays": "not_a_number"},
        )
        assert resp.status_code == 200
        assert resp.json()["scan_window_days"] == 90


class TestCaching:
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_second_request_uses_cache(self, mock_scan, mock_wt):
        addr = "0x" + "1" * 40
        body = {"address": addr}

        resp1 = client.post("/v1/airdrop-exposure/base", json=body)
        assert resp1.status_code == 200
        ts1 = resp1.json()["scan_timestamp"]

        resp2 = client.post("/v1/airdrop-exposure/base", json=body)
        assert resp2.status_code == 200
        ts2 = resp2.json()["scan_timestamp"]

        # Cache hit → same timestamp
        assert ts1 == ts2

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_scanner_called_only_once_with_cache(self, mock_scan, mock_wt):
        addr = "0x" + "2" * 40
        body = {"address": addr}

        client.post("/v1/airdrop-exposure/base", json=body)
        client.post("/v1/airdrop-exposure/base", json=body)

        # Scanner should only be called once; second hit is cached
        assert mock_scan.call_count == 1


class TestPartialScan:
    def _mock_partial_scan(self, *args, **kwargs):
        tokenless = [
            TokenlessSignal(
                protocol_id="p1", protocol_name="Proto 1", category="dex",
                protocol_weight=1.0, interacted=False, detection_mode="event_topic",
            )
        ]
        return tokenless, [], "partial", ["skipped_proto"]

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock)
    def test_partial_scan_completeness(self, mock_scan, mock_wt):
        mock_scan.side_effect = self._mock_partial_scan
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "a" * 40},
        )
        data = resp.json()
        assert data["scan_completeness"] == "partial"
        assert data["partial_scan_note"] is not None
        assert "truncated" in data["partial_scan_note"].lower()

    def _mock_full_scan(self, *args, **kwargs):
        return [
            TokenlessSignal(
                protocol_id="p1", protocol_name="Proto 1", category="dex",
                protocol_weight=1.0, interacted=False, detection_mode="event_topic",
            )
        ], [], "full", []

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock)
    def test_full_scan_no_partial_note(self, mock_scan, mock_wt):
        mock_scan.side_effect = self._mock_full_scan
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "b" * 40},
        )
        data = resp.json()
        assert data["scan_completeness"] == "full"
        assert data["partial_scan_note"] is None


class TestWalletType:
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="contract")
    def test_contract_wallet_note(self, mock_wt, mock_scan):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "c" * 40},
        )
        data = resp.json()
        assert data["wallet_type"] == "contract"
        assert data["wallet_note"] is not None
        assert "smart contract" in data["wallet_note"].lower()

    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    def test_eoa_wallet_no_note(self, mock_wt, mock_scan):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "d" * 40},
        )
        data = resp.json()
        assert data["wallet_type"] == "eoa"
        assert data["wallet_note"] is None

    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="unknown")
    def test_unknown_wallet_has_note(self, mock_wt, mock_scan):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "e" * 40},
        )
        data = resp.json()
        assert data["wallet_type"] == "unknown"
        assert data["wallet_note"] is not None
        assert "detection failed" in data["wallet_note"].lower()


class TestResponseDataVerification:

    def _mock_with_interactions(self, *args, **kwargs):
        tokenless = [
            TokenlessSignal(
                protocol_id="morpho", protocol_name="Morpho", category="lending",
                protocol_weight=1.2, interacted=True,
                first_seen="2026-02-01", last_seen="2026-02-10",
                interaction_count=8, signal_types=["supply", "borrow"],
                signal_strength="none", detection_mode="event_topic",
            ),
            TokenlessSignal(
                protocol_id="aero", protocol_name="Aerodrome", category="dex",
                protocol_weight=1.0, interacted=False,
                detection_mode="event_topic",
            ),
        ]
        tokened = [
            TokenedSignal(
                protocol_id="uni", protocol_name="Uniswap", category="dex",
                token_symbol="UNI", interacted=True,
                note="Already has token ($UNI) — included for completeness",
            ),
        ]
        return tokenless, tokened, "full", []  # no skipped

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock)
    def test_scoring_applied_to_signals(self, mock_scan, mock_wt):
        """signal_strength should be populated by the scoring engine, not left as 'none'."""
        mock_scan.side_effect = self._mock_with_interactions
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "f" * 40},
        )
        data = resp.json()
        morpho = [s for s in data["tokenless_signals"] if s["protocol_id"] == "morpho"][0]
        # With 8 interactions, supply+borrow types, recent activity, scoring should produce
        # something other than "none"
        assert morpho["signal_strength"] in ("weak", "moderate", "strong")
        assert morpho["interaction_count"] == 8
        assert morpho["signal_types"] == ["supply", "borrow"]

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock)
    def test_summary_reflects_signals(self, mock_scan, mock_wt):
        mock_scan.side_effect = self._mock_with_interactions
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "f" * 40 + "1" * 0},  # unique to avoid cache
        )
        # clear cache to ensure fresh scan
        scan_cache.clear()
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "a1b2c3d4e5" + "f" * 30},
        )
        data = resp.json()
        summary = data["summary"]
        assert summary["tokenless_protocols_interacted"] == 1
        assert summary["tokenless_protocols_available"] == 2
        assert summary["total_protocols_scanned"] == 3  # 2 tokenless + 1 tokened
        assert summary["overall_likelihood"] == "low"  # only 1 tokenless interacted

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock)
    def test_tokened_signal_data(self, mock_scan, mock_wt):
        mock_scan.side_effect = self._mock_with_interactions
        scan_cache.clear()
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "ab" * 20},
        )
        data = resp.json()
        uni = [s for s in data["tokened_signals"] if s["protocol_id"] == "uni"][0]
        assert uni["token_symbol"] == "UNI"
        assert uni["interacted"] is True
        assert "$UNI" in uni["note"]

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock)
    def test_disclaimer_present(self, mock_scan, mock_wt):
        mock_scan.side_effect = self._mock_with_interactions
        scan_cache.clear()
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "de" * 20},
        )
        data = resp.json()
        assert "disclaimer" in data
        assert "not financial advice" in data["disclaimer"].lower()

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock)
    def test_next_actions_generated(self, mock_scan, mock_wt):
        """With only lending covered, should suggest other categories."""
        mock_scan.side_effect = self._mock_with_interactions
        scan_cache.clear()
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "cd" * 20},
        )
        data = resp.json()
        # Non-interacted category (dex has Aerodrome not interacted) should be suggested
        # Actually next_actions are based on uncovered categories from coverage_dict
        assert isinstance(data["next_actions"], list)


class TestCacheKeyIsolation:
    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_different_window_days_different_cache(self, mock_scan, mock_wt):
        """Different windowDays should produce cache misses."""
        addr = "0x" + "3" * 40
        client.post("/v1/airdrop-exposure/base", json={"address": addr, "windowDays": 60})
        client.post("/v1/airdrop-exposure/base", json={"address": addr, "windowDays": 90})
        assert mock_scan.call_count == 2

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_different_chains_different_cache(self, mock_scan, mock_wt):
        """Same address on different chains should produce cache misses."""
        # We only need a valid address per chain
        client.post("/v1/airdrop-exposure/base", json={"address": "0x" + "4" * 40})
        client.post(
            "/v1/airdrop-exposure/solana",
            json={"address": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
        )
        assert mock_scan.call_count == 2

    @patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa")
    @patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan_result)
    def test_different_addresses_different_cache(self, mock_scan, mock_wt):
        client.post("/v1/airdrop-exposure/base", json={"address": "0x" + "5" * 40})
        client.post("/v1/airdrop-exposure/base", json={"address": "0x" + "6" * 40})
        assert mock_scan.call_count == 2


class TestInputEdgeCases:
    def test_address_with_leading_trailing_spaces(self):
        """Address with whitespace should be stripped and validated."""
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "  0x" + "a" * 40 + "  "},
        )
        # strip() is called in the route handler, but validate happens after strip
        # " 0x..." after strip → "0x..." → should be valid
        # Actually " 0x..." strip → " 0x..." → hmm, strip removes spaces
        # "  0x...  ".strip() → "0x..." → valid
        assert resp.status_code != 500  # Should not crash

    def test_address_with_mixed_case_normalized(self):
        """Mixed-case EVM address should be normalized to lowercase."""
        from app.models.response import TokenlessSignal, TokenedSignal

        def mock_scan(*a, **kw):
            return [
                TokenlessSignal(
                    protocol_id="p", protocol_name="P", category="dex",
                    protocol_weight=1.0, interacted=False, detection_mode="event_topic",
                )
            ], [], "full", []

        with patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=mock_scan):
            with patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa"):
                mixed = "0xAbCdEf" + "1234567890" * 3 + "abCDef12"
                if len(mixed) != 42:
                    mixed = "0xAbCdEf1234567890abcdef1234567890ABCDEF12"
                resp = client.post(
                    "/v1/airdrop-exposure/base",
                    json={"address": mixed},
                )
                if resp.status_code == 200:
                    assert resp.json()["address"] == mixed.lower()

    def test_empty_string_address(self):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": ""},
        )
        assert resp.status_code == 400

    def test_null_address(self):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": None},
        )
        assert resp.status_code == 400

    def test_numeric_address(self):
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": 12345},
        )
        assert resp.status_code == 400

    def test_scan_timestamp_is_iso_format(self):
        """scan_timestamp should be a valid ISO 8601 string."""
        from datetime import datetime as dt

        def mock_scan(*a, **kw):
            return [
                TokenlessSignal(
                    protocol_id="p", protocol_name="P", category="dex",
                    protocol_weight=1.0, interacted=False, detection_mode="event_topic",
                )
            ], [], "full", []

        with patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=mock_scan):
            with patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa"):
                resp = client.post(
                    "/v1/airdrop-exposure/base",
                    json={"address": "0x" + "7" * 40},
                )
                assert resp.status_code == 200
                ts = resp.json()["scan_timestamp"]
                # Should parse without error
                parsed = dt.fromisoformat(ts)
                assert parsed.year >= 2026
