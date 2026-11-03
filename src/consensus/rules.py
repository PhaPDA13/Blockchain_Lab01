"""
Consensus locking state and validation rules per Section 6.1 of Lab 01.
"""
from typing import Optional, Dict, Set, Tuple
from .vote import Vote, VoteType


class ConsensusLockState:
    """
    Maintains consensus locking state for a single node across heights and rounds.
    Implements rules 1, 2, 4, 5, 6, 7.
    """

    def __init__(self):
        # Locked block and round for current height
        self.locked_block_hash: Optional[str] = None
        self.locked_round: int = -1

        # Track votes signed by this validator to enforce at most 1 vote per (height, round, phase)
        # Key: (height, round, phase) -> block_hash
        self._signed_votes: Dict[Tuple[int, int, str], str] = {}

        # Votes received from peers: (height, round, phase, validator_pk) -> Vote
        # Enforces Rule 7: count at most one valid vote per validator for (height, round, phase)
        self._received_votes: Dict[Tuple[int, int, str, str], Vote] = {}

    def reset_for_height(self):
        """Reset locking state when advancing to a new height."""
        self.locked_block_hash = None
        self.locked_round = -1

    def can_sign_vote(self, height: int, round: int, phase: VoteType) -> bool:
        """Rules 1 & 2: At most one PREVOTE and one PRECOMMIT per (height, round)."""
        key = (height, round, phase.value)
        return key not in self._signed_votes

    def record_signed_vote(self, height: int, round: int, phase: VoteType, block_hash: Optional[str]):
        """Record vote signed by this validator."""
        key = (height, round, phase.value)
        self._signed_votes[key] = block_hash or ""

    def can_prevote_block(self, block_hash: str, current_round: int, quorum_prevote_hash: Optional[str], quorum_round: int) -> bool:
        """
        Rule 5: A validator locked on block B may prevote a different block only
        after it observes a quorum of valid PREVOTE messages for that different block
        in a later round.
        """
        if self.locked_block_hash is None:
            return True
        if block_hash == self.locked_block_hash:
            return True
        # Unlock condition: observed quorum of PREVOTE for different block in later round
        if quorum_prevote_hash == block_hash and quorum_round > self.locked_round:
            return True
        return False

    def update_lock_on_prevote_quorum(self, block_hash: Optional[str], round: int):
        """
        Rule 4: When a validator observes a quorum of PREVOTE messages for a non-NIL block,
        it locks that block and records the corresponding round.
        """
        if block_hash:
            self.locked_block_hash = block_hash
            self.locked_round = round

    def add_received_vote(self, vote: Vote, chain_id: str, validator_set: Set[str]) -> bool:
        """
        Rule 7: Nodes must ignore duplicate votes and must count at most one valid vote
        from each validator for a given (height, round, phase).
        Returns True if vote is accepted as new valid vote, False if duplicate or invalid.
        """
        if vote.validator not in validator_set:
            return False

        if not vote.is_valid(chain_id):
            return False

        key = (vote.height, vote.round, vote.phase.value, vote.validator)
        if key in self._received_votes:
            # Duplicate vote - ignore
            return False

        self._received_votes[key] = vote
        return True

    def get_votes_for_phase(self, height: int, round: int, phase: VoteType) -> Dict[str, Vote]:
        """Get all accepted unique votes for (height, round, phase)."""
        res = {}
        target_phase = phase.value
        for (h, r, p, val_pk), vote in self._received_votes.items():
            if h == height and r == round and p == target_phase:
                res[val_pk] = vote
        return res
