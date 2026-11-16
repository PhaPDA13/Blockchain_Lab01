"""
BFT Consensus Engine implementing 2-phase agreement (Prevote and Precommit).
For n validators and f = floor((n - 1) / 3), quorum = n - f.
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
        if not self.validators or len(set(self.validators)) != len(self.validators):
            raise ValueError("The validator set must be non-empty and contain unique keys.")
        if key_pair.public_key_hex not in self.validators:
            raise ValueError("This node's public key must belong to the validator set.")
        self.n = len(self.validators)
        if self.n < 4 or (self.n - 1) % 3 != 0:
            raise ValueError("Validator count must satisfy n = 3f + 1.")
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

        if block_hash and self.lock_state.locked_block_hash not in (None, block_hash):
            quorum_round = self._latest_prevote_quorum_round(block_hash)
            if not self.lock_state.can_prevote_block(
                block_hash,
                self.round,
                block_hash,
                quorum_round,
            ):
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
        self.add_received_vote(vote)  # A validator's own vote counts toward quorum.
        return vote

    def create_precommit(self, block_hash: Optional[str]) -> Optional[Vote]:
        """Sign and return a PRECOMMIT for the current (height, round)."""
        if not self.lock_state.can_sign_vote(self.height, self.round, VoteType.PRECOMMIT):
            return None
        if not self.has_prevote_quorum(block_hash, self.height, self.round):
            return None

        if block_hash:
            self.lock_state.update_lock_on_prevote_quorum(block_hash, self.round)

        vote = Vote(
            validator=self.key_pair.public_key_hex,
            height=self.height,
            round=self.round,
            phase=VoteType.PRECOMMIT,
            block_hash=block_hash,
        )
        vote.sign(self.key_pair, self.chain_id)
        self.lock_state.record_signed_vote(self.height, self.round, VoteType.PRECOMMIT, block_hash)
        self.add_received_vote(vote)  # A validator's own vote counts toward quorum.
        return vote

    def add_received_vote(self, vote: Vote) -> bool:
        """Validate a peer vote and update the lock when a prevote quorum forms."""
        if (
            vote.height != self.height
            or vote.round < 0
            or vote.round > self.round
            or not isinstance(vote.phase, VoteType)
        ):
            return False

        accepted = self.lock_state.add_received_vote(
            vote=vote,
            chain_id=self.chain_id,
            validator_set=set(self.validators),
        )
        if accepted and vote.phase == VoteType.PREVOTE:
            self._record_prevote_quorum(vote.height, vote.round)
        return accepted

    def has_prevote_quorum(
        self,
        block_hash: Optional[str],
        height: int,
        round: int,
    ) -> bool:
        """Return whether one candidate, including NIL, has a prevote quorum."""
        target = block_hash or ""
        votes = self.lock_state.get_votes_for_phase(height, round, VoteType.PREVOTE)
        return sum((vote.block_hash or "") == target for vote in votes.values()) >= self.quorum_size

    def _record_prevote_quorum(self, height: int, round: int) -> Optional[str]:
        block_hash = self.check_prevote_quorum(height, round)
        if block_hash:
            self.lock_state.update_lock_on_prevote_quorum(block_hash, round)
        return block_hash

    def _latest_prevote_quorum_round(self, block_hash: str) -> int:
        """Find a later-round justification observed before the current round."""
        first_round = max(0, self.lock_state.locked_round + 1)
        for round_number in range(self.round - 1, first_round - 1, -1):
            if self.has_prevote_quorum(block_hash, self.height, round_number):
                return round_number
        return -1

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

    def verify_precommit_certificate(
        self, votes: List[Vote], block_hash: str, height: int, round: int
    ) -> bool:
        """Verify a portable finality proof without relying on local vote history."""
        validators: Set[str] = set()
        validator_set = set(self.validators)
        for vote in votes:
            if (
                vote.validator not in validator_set
                or vote.validator in validators
                or vote.height != height
                or vote.round != round
                or vote.phase != VoteType.PRECOMMIT
                or vote.block_hash != block_hash
                or not vote.is_valid(self.chain_id)
            ):
                return False
            validators.add(vote.validator)
        return len(validators) >= self.quorum_size

    def advance_to_next_height(self):
        """Finalization complete: advance height and reset round and locks."""
        self.height += 1
        self.round = 0
        self.step = "PROPOSE"
        self.lock_state.reset_for_height(self.height)
        self.blocks.clear()

    def advance_to_next_round(self):
        """Round timeout or failed consensus: advance round while maintaining locks."""
        self.round += 1
        self.step = "PROPOSE"
