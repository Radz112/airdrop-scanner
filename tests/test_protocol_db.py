from __future__ import annotations

from app.services.protocol_db import ProtocolDB, protocol_db


class TestProtocolDBLoading:
    def test_global_instance_loads(self):
        """The global protocol_db should load without errors."""
        protocol_db.load()
        assert protocol_db.count > 0

    def test_load_is_idempotent(self):
        """Calling load() twice should not duplicate protocols."""
        protocol_db.load()
        count1 = protocol_db.count
        protocol_db.load()
        count2 = protocol_db.count
        assert count1 == count2

    def test_all_protocols_returns_list(self):
        protocol_db.load()
        all_protos = protocol_db.all_protocols()
        assert isinstance(all_protos, list)
        assert len(all_protos) == protocol_db.count


class TestProtocolDBQuerying:
    def test_get_by_chain_base(self):
        protocol_db.load()
        base_protos = protocol_db.get_by_chain("base")
        assert len(base_protos) > 0
        assert all(p.chain == "base" for p in base_protos)

    def test_get_by_chain_solana(self):
        protocol_db.load()
        sol_protos = protocol_db.get_by_chain("solana")
        assert len(sol_protos) > 0
        assert all(p.chain == "solana" for p in sol_protos)

    def test_get_by_chain_nonexistent(self):
        protocol_db.load()
        result = protocol_db.get_by_chain("ethereum")
        assert result == []

    def test_get_protocol_by_id(self):
        protocol_db.load()
        all_protos = protocol_db.all_protocols()
        if all_protos:
            p = all_protos[0]
            fetched = protocol_db.get(p.id)
            assert fetched is not None
            assert fetched.id == p.id

    def test_get_nonexistent_protocol(self):
        protocol_db.load()
        assert protocol_db.get("nonexistent_id_xyz") is None


class TestProtocolDBFiltering:
    def test_get_tokenless(self):
        protocol_db.load()
        tokenless = protocol_db.get_tokenless("base")
        assert all(p.has_token is False for p in tokenless)

    def test_get_tokened(self):
        protocol_db.load()
        tokened = protocol_db.get_tokened("base")
        assert all(p.has_token is True for p in tokened)

    def test_tokenless_plus_tokened_equals_all(self):
        protocol_db.load()
        for chain in ("base", "solana"):
            all_chain = protocol_db.get_by_chain(chain)
            tokenless = protocol_db.get_tokenless(chain)
            tokened = protocol_db.get_tokened(chain)
            assert len(tokenless) + len(tokened) == len(all_chain)


class TestProtocolDBDataIntegrity:
    def test_all_protocols_have_required_fields(self):
        protocol_db.load()
        for p in protocol_db.all_protocols():
            assert p.id
            assert p.name
            assert p.chain
            assert p.category

    def test_all_protocols_have_valid_category(self):
        """Every protocol category should be one of the known categories."""
        from app.models.protocol import ProtocolCategory
        valid = {e.value for e in ProtocolCategory}

        protocol_db.load()
        for p in protocol_db.all_protocols():
            assert p.category.value in valid, f"{p.id} has invalid category: {p.category}"

    def test_all_contracts_have_valid_detection_mode(self):
        from app.models.protocol import DetectionMode
        valid = {e.value for e in DetectionMode}

        protocol_db.load()
        for p in protocol_db.all_protocols():
            for c in p.contracts:
                assert c.detection_mode.value in valid, \
                    f"{p.id}/{c.label} has invalid mode: {c.detection_mode}"

    def test_tokened_protocols_have_token_symbol(self):
        protocol_db.load()
        for p in protocol_db.all_protocols():
            if p.has_token:
                assert p.token_symbol, f"{p.id} has_token=True but no token_symbol"

    def test_protocol_weights_positive(self):
        protocol_db.load()
        for p in protocol_db.all_protocols():
            assert p.protocol_weight > 0, f"{p.id} has non-positive weight: {p.protocol_weight}"
