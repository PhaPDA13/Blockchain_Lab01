"""
Cryptographic hashing and state commitments (SHA-256).
"""
import hashlib
from typing import Dict, Any
from .encoding import canonical_encode


def hash_bytes(data: bytes) -> str:
    """Compute hex SHA-256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_data(data: Any) -> str:
    """Compute hex SHA-256 hash of data using canonical encoding."""
    return hash_bytes(canonical_encode(data))


def compute_state_root(state: Dict[str, Any]) -> str:
    """
    Compute a deterministic commitment hash for the key-value state.
    Uses canonical encoding of sorted key-value pairs.
    """
    sorted_items = sorted(state.items())
    return hash_data(sorted_items)
