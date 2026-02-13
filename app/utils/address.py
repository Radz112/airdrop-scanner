import re


def pad_evm_address(address: str) -> str:
    """Pad an EVM address to 32 bytes for topic filtering."""
    return "0x" + address.lower().replace("0x", "").zfill(64)


def validate_evm_address(address: str) -> bool:
    return bool(re.match(r"^0x[0-9a-fA-F]{40}$", address))


def validate_solana_address(address: str) -> bool:
    """Validate a Solana base58 address (32-44 chars, base58 alphabet)."""
    return bool(re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", address))


def validate_address(address: str, chain: str) -> bool:
    if chain == "base":
        return validate_evm_address(address)
    elif chain == "solana":
        return validate_solana_address(address)
    return False


def normalize_address(address: str, chain: str) -> str:
    if chain == "base":
        return address.lower()
    return address
