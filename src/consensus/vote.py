"""
Vote definition and verification for Prevote and Precommit phases.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional
from ..crypto.identity import KeyPair, verify_signature


class VoteType(str, Enum):
    PREVOTE = "PREVOTE"
    PRECOMMIT = "PRECOMMIT"


@dataclass
class Vote:
    validator: str       # Public key of validator
    height: int
    round: int
    phase: VoteType      # PREVOTE or PRECOMMIT
    block_hash: Optional[str]  # None or empty string indicates NIL vote
    signature: str = ""

    def payload_dict(self) -> Dict[str, Any]:
        """Dictionary used for vote signature and verification."""
        return {
            "validator": self.validator,
            "height": self.height,
            "round": self.round,
            "phase": self.phase.value if isinstance(self.phase, VoteType) else str(self.phase),
            "block_hash": self.block_hash or "",
        }

    def sign(self, key_pair: KeyPair, chain_id: str):
        """Sign vote under context VOTE:{chain_id}."""
        context = f"VOTE:{chain_id}"
        self.signature = key_pair.sign(self.payload_dict(), context)

    def is_valid(self, chain_id: str) -> bool:
        """Verify vote signature under context VOTE:{chain_id}."""
        if not self.signature:
            return False
        context = f"VOTE:{chain_id}"
        return verify_signature(
            public_key_hex=self.validator,
            message_data=self.payload_dict(),
            signature_hex=self.signature,
            context=context,
        )
