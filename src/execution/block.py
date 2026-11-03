"""
Block and BlockHeader data structures.
Rules:
- Header commits to parent_hash, height, and resulting state_root.
- Header is signed by proposer under context HEADER:{chain_id}.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any
from .transaction import Transaction
from ..crypto.identity import KeyPair, verify_signature
from ..crypto.hashing import hash_data


@dataclass
class BlockHeader:
    parent_hash: str
    height: int
    round: int
    state_root: str
    proposer: str
    signature: str = ""

    def payload_dict(self) -> Dict[str, Any]:
        """Dictionary used for hashing and signature (excluding signature)."""
        return {
            "parent_hash": self.parent_hash,
            "height": self.height,
            "round": self.round,
            "state_root": self.state_root,
            "proposer": self.proposer,
        }

    @property
    def header_hash(self) -> str:
        """Deterministic block hash computed from header payload."""
        return hash_data(self.payload_dict())

    def sign(self, key_pair: KeyPair, chain_id: str):
        """Sign header under context HEADER:{chain_id}."""
        context = f"HEADER:{chain_id}"
        self.signature = key_pair.sign(self.payload_dict(), context)

    def is_valid_signature(self, chain_id: str) -> bool:
        """Verify header signature from proposer."""
        if not self.signature:
            return False
        context = f"HEADER:{chain_id}"
        return verify_signature(
            public_key_hex=self.proposer,
            message_data=self.payload_dict(),
            signature_hex=self.signature,
            context=context,
        )


@dataclass
class Block:
    header: BlockHeader
    transactions: List[Transaction] = field(default_factory=list)

    @property
    def block_hash(self) -> str:
        return self.header.header_hash
