"""
Identity and signature layer with Ed25519 and domain separation context strings.
Required contexts:
- TX:{chain_id}
- HEADER:{chain_id}
- VOTE:{chain_id}
"""
from typing import Tuple
from cryptography.hazmat.primitives.asymmetric import ed25519
from .encoding import canonical_encode


class KeyPair:
    """Manages an Ed25519 public/private keypair."""

    def __init__(self, private_key: ed25519.Ed25519PrivateKey = None):
        if private_key is None:
            self._private_key = ed25519.Ed25519PrivateKey.generate()
        else:
            self._private_key = private_key
        self._public_key = self._private_key.public_key()

    @classmethod
    def from_seed(cls, seed: bytes) -> "KeyPair":
        """Deterministic key generation from 32-byte seed."""
        assert len(seed) == 32, "Seed must be 32 bytes"
        priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        return cls(priv)

    @property
    def public_key_hex(self) -> str:
        """Hex encoded public key."""
        raw_bytes = self._public_key.public_bytes_raw()
        return raw_bytes.hex()

    def sign(self, message_data: dict, context: str) -> str:
        """
        Sign message payload bound with domain separation context.
        Sign( context_bytes + canonical_encode(message_data) )
        """
        payload = context.encode("utf-8") + b":" + canonical_encode(message_data)
        signature = self._private_key.sign(payload)
        return signature.hex()


def verify_signature(
    public_key_hex: str,
    message_data: dict,
    signature_hex: str,
    context: str,
) -> bool:
    """
    Verify Ed25519 signature under the specified domain separation context.
    Returns False if signature or context is invalid.
    """
    try:
        pub_bytes = bytes.fromhex(public_key_hex)
        sig_bytes = bytes.fromhex(signature_hex)
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        payload = context.encode("utf-8") + b":" + canonical_encode(message_data)
        pub_key.verify(sig_bytes, payload)
        return True
    except Exception:
        return False
