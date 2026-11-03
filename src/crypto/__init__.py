"""
Cryptography layer: Deterministic encoding, hashing, and signature with domain separation.
"""
from .encoding import canonical_encode
from .hashing import hash_data, compute_state_root
from .identity import KeyPair, verify_signature

__all__ = [
    "canonical_encode",
    "hash_data",
    "compute_state_root",
    "KeyPair",
    "verify_signature",
]
