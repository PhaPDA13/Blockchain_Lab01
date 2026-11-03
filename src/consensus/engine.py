"""
BFT Consensus Engine implementing 2-phase agreement (Prevote and Precommit).
n = 3f + 1, quorum = 2f + 1.
"""
from typing import List, Set, Optional, Dict
from .vote import Vote, VoteType
from .rules import ConsensusLockState
from ..execution.block import Block, BlockHeader
from ..crypto.identity import KeyPair


class ConsensusEngine:
    """Manages consensus rounds and state machine transitions."""

    def __init__(
        self,
        node_id: str,
        key_pair: KeyPair,
        chain_id: str,
        validators: List[str],  # List of validator public keys
    ):
        self.node_id = node_id
        self.key_pair = key_pair
        self.chain_id = chain_id
        self.validators = sorted(validators)
        self.n = len(self.validators)
        self.f = (self.n - 1) // 3
        self.quorum_size = 2 * self.f + 1

        self.height = 1
        self.round = 0
        self.step = "PROPOSE"  # PROPOSE, PREVOTE, PRECOMMIT
        self.lock_state = ConsensusLockState()

        # Proposed blocks at current height: block_hash -> Block
        self.blocks: Dict[str, Block] = {}

    def get_proposer(self, height: int, round: int) -> str:
        """Deterministic round-robin proposer selection."""
        idx = (height + round) % self.n
        return self.validators[idx]

    def is_current_proposer(self) -> bool:
        """Check if this node is proposer for current (height, round)."""
        return self.get_proposer(self.height, self.round) == self.key_pair.public_key_hex

    def create_prevote(self, block_hash: Optional[str]) -> Optional[Vote]:
        """Sign and return a PREVOTE for the current (height, round)."""
        if not self.lock_state.can_sign_vote(self.height, self.round, VoteType.PREVOTE):
            return None

        vote = Vote(
            validator=self.key_pair.public_key_hex,
            height=self.height,
            round=self.round,
            phase=VoteType.PREVOTE,
            block_hash=block_hash,
        )
        vote.sign(self.key_pair, self.chain_id)
        self.lock_state.record_signed_vote(self.height, self.round, VoteType.PREVOTE, block_hash)
        return vote

    def create_precommit(self, block_hash: Optional[str]) -> Optional[Vote]:
        """Sign and return a PRECOMMIT for the current (height, round)."""
        if not self.lock_state.can_sign_vote(self.height, self.round, VoteType.PRECOMMIT):
            return None

        vote = Vote(
            validator=self.key_pair.public_key_hex,
            height=self.height,
            round=self.round,
            phase=VoteType.PRECOMMIT,
            block_hash=block_hash,
        )
        vote.sign(self.key_pair, self.chain_id)
        self.lock_state.record_signed_vote(self.height, self.round, VoteType.PRECOMMIT, block_hash)
        return vote

    def check_prevote_quorum(self, height: int, round: int) -> Optional[str]:
        """
        Check if any block_hash (including NIL) has accumulated >= 2f + 1 prevotes.
        Returns the block_hash if quorum reached, else None.
        """
        votes = self.lock_state.get_votes_for_phase(height, round, VoteType.PREVOTE)
        counts: Dict[str, int] = {}
        for vote in votes.values():
            h = vote.block_hash or ""
            counts[h] = counts.get(h, 0) + 1
            if counts[h] >= self.quorum_size:
                return vote.block_hash
        return None

    def check_precommit_quorum(self, height: int, round: int) -> Optional[str]:
        """
        Check if any block_hash (excluding NIL) has accumulated >= 2f + 1 precommits.
        Returns the finalized block_hash if quorum reached, else None.
        """
        votes = self.lock_state.get_votes_for_phase(height, round, VoteType.PRECOMMIT)
        counts: Dict[str, int] = {}
        for vote in votes.values():
            if not vote.block_hash:
                continue  # Precommits for NIL do not finalize
            h = vote.block_hash
            counts[h] = counts.get(h, 0) + 1
            if counts[h] >= self.quorum_size:
                return h
        return None

    def advance_to_next_height(self):
        """Finalization complete: advance height and reset round and locks."""
        self.height += 1
        self.round = 0
        self.step = "PROPOSE"
        self.lock_state.reset_for_height()
        self.blocks.clear()

    def advance_to_next_round(self):
        """Round timeout or failed consensus: advance round while maintaining locks."""
        self.round += 1
        self.step = "PROPOSE"
