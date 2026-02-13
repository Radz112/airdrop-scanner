from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models.protocol import Protocol

logger = logging.getLogger("protocol_db")

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "protocols"


class ProtocolDB:
    def __init__(self):
        self._protocols: dict[str, Protocol] = {}
        self._by_chain: dict[str, list[Protocol]] = {}

    def load(self) -> None:
        self._protocols.clear()
        self._by_chain.clear()

        for chain_dir in _DATA_DIR.iterdir():
            if not chain_dir.is_dir() or chain_dir.name.startswith("."):
                continue
            chain = chain_dir.name
            self._by_chain.setdefault(chain, [])

            for proto_file in sorted(chain_dir.glob("*.json")):
                try:
                    data = json.loads(proto_file.read_text())
                    protocol = Protocol(**data)
                    self._protocols[protocol.id] = protocol
                    self._by_chain[chain].append(protocol)
                except Exception as e:
                    logger.error(f"Failed to load {proto_file}: {e}")

        total = len(self._protocols)
        chains = {p.chain for p in self._protocols.values()}
        logger.info(f"Loaded {total} protocols across chains: {chains}")

    def get(self, protocol_id: str) -> Protocol | None:
        return self._protocols.get(protocol_id)

    def get_by_chain(self, chain: str) -> list[Protocol]:
        return self._by_chain.get(chain, [])

    def get_tokenless(self, chain: str) -> list[Protocol]:
        return [p for p in self.get_by_chain(chain) if not p.has_token]

    def get_tokened(self, chain: str) -> list[Protocol]:
        return [p for p in self.get_by_chain(chain) if p.has_token]

    def all_protocols(self) -> list[Protocol]:
        return list(self._protocols.values())

    @property
    def count(self) -> int:
        return len(self._protocols)


protocol_db = ProtocolDB()
