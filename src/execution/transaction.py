"""
Transaction definition, signing, and verification.
Rules:
- Domain context: TX:{chain_id}
- Ownership: Transaction affects only data owned by its sender (e.g. key prefixed with sender_id or sender_pubkey)
- Replay protection via nonce and unique transaction hash.
"""
from dataclasses import dataclass, asdict
from typing import Dict, Any
from ..crypto.identity import KeyPair, verify_signature
from ..crypto.hashing import hash_data


@dataclass
class Transaction:
    sender: str       # Public key or identity prefix
    key: str          # State key being updated (must start with sender)
    value: str        # New state value
    nonce: int        # Anti-replay nonce
    signature: str = ""

    def payload_dict(self) -> Dict[str, Any]:
        """Dictionary used for signature and hashing (excluding signature itself)."""
        return {
            "sender": self.sender,
            "key": self.key,
            "value": self.value,
            "nonce": self.nonce,
        }

    @property
    def tx_hash(self) -> str:
        """Deterministic transaction hash."""
        return hash_data(self.payload_dict())

    def sign(self, key_pair: KeyPair, chain_id: str):
        """Sign this transaction under context TX:{chain_id}."""
        context = f"TX:{chain_id}"
        self.signature = key_pair.sign(self.payload_dict(), context)

    def is_valid(self, chain_id: str) -> bool:
        """
        Validate transaction ownership, context, and signature.
        Ownership rule: key must be owned by sender (e.g., key.startswith(sender + "/")).
        """
        # Ownership check
        if not self.key.startswith(f"{self.sender}/"):
            return False

        if not self.signature:
            return False

        context = f"TX:{chain_id}"
        return verify_signature(
            public_key_hex=self.sender,
            message_data=self.payload_dict(),
            signature_hex=self.signature,
            context=context,
        )
