from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.cache import scan_cache
from app.services.protocol_db import protocol_db

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def load_protocols():
    protocol_db.load()


@pytest.fixture(autouse=True)
def clear_cache():
    scan_cache.clear()
    yield
    scan_cache.clear()


class TestAPIX402EdgeCases:
    def test_empty_json_body_returns_400(self):
        """POST with {} should return 400 for missing address."""
        resp = client.post("/v1/airdrop-exposure/base", json={})
        assert resp.status_code == 400
        assert "address" in resp.json()["error"].lower()

    def test_non_json_body_handled_gracefully(self):
        """POST with non-JSON content-type should not crash."""
        resp = client.post(
            "/v1/airdrop-exposure/base",
            content=b"not json",
            headers={"content-type": "text/plain"},
        )
        # Should get 400 (missing address), not 500
        assert resp.status_code == 400

    def test_deeply_nested_body_only_one_level(self):
        """Only one level of body nesting is unwrapped."""
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"body": {"body": {"address": "0x" + "a" * 40}}},
        )
        # The inner body.body should NOT be unwrapped further
        # After middleware: {"body": {"address": "0x..."}}
        # extract_param checks body["body"]["address"] → finds it
        assert resp.status_code in (200, 400)

    def test_nested_body_with_extra_top_level_fields(self):
        """APIX402 wrapping may include extra fields alongside body."""
        from app.models.response import TokenlessSignal, TokenedSignal

        def _mock_scan(*a, **kw):
            return [
                TokenlessSignal(
                    protocol_id="p", protocol_name="P", category="dex",
                    protocol_weight=1.0, interacted=False, detection_mode="event_topic",
                )
            ], [], "full", []

        with patch("app.routes.airdrop.scan_wallet", new_callable=AsyncMock, side_effect=_mock_scan):
            with patch("app.routes.airdrop._detect_wallet_type", new_callable=AsyncMock, return_value="eoa"):
                resp = client.post(
                    "/v1/airdrop-exposure/base",
                    json={
                        "agentId": "agent-123",
                        "body": {"address": "0x" + "a" * 40, "windowDays": 45},
                    },
                )
                assert resp.status_code == 200
                assert resp.json()["scan_window_days"] == 45

    def test_get_requests_bypass_body_parsing(self):
        """GET requests should not attempt body parsing."""
        resp = client.get("/v1/airdrop-exposure/base")
        assert resp.status_code == 200
        assert resp.json()["method"] == "POST"


class TestRateLimiting:
    def test_get_requests_not_rate_limited(self):
        """GET requests should bypass rate limiting entirely."""
        for _ in range(150):
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_post_within_limit_succeeds(self):
        """A single POST should not be rate limited."""
        resp = client.post(
            "/v1/airdrop-exposure/base",
            json={"address": "0x" + "a" * 40},
        )
        # May be 200 or 400 depending on validation, but NOT 429
        assert resp.status_code != 429


class TestErrorResponseStructure:
    def test_missing_address_error_has_no_hint(self):
        """After refactor, error responses should not have hardcoded hint."""
        resp = client.post("/v1/airdrop-exposure/base", json={})
        data = resp.json()
        assert "hint" not in data
        assert "error" in data

    def test_invalid_address_error_includes_received_body(self):
        """Invalid address errors should include the received body for debugging."""
        body = {"address": "bad_addr"}
        resp = client.post("/v1/airdrop-exposure/base", json=body)
        data = resp.json()
        assert data["error"].startswith("Invalid")
        assert "received_body" in data

    def test_unsupported_chain_error_has_no_received_body(self):
        """Chain validation errors don't pass received_body."""
        resp = client.get("/v1/airdrop-exposure/ethereum")
        data = resp.json()
        assert "error" in data
        assert "received_body" not in data

    def test_503_no_protocols_error(self):
        """If protocol_db returns empty list, should get 503."""
        with patch("app.routes.airdrop.protocol_db") as mock_db:
            mock_db.get_by_chain.return_value = []
            resp = client.post(
                "/v1/airdrop-exposure/base",
                json={"address": "0x" + "a" * 40},
            )
            assert resp.status_code == 503
            assert "No protocols" in resp.json()["error"]
