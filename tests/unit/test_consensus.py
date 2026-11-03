"""
Unit tests for consensus vote counting, locking rules, and quorum calculation.
"""
import pytest
from src.crypto.identity import KeyPair
from src.consensus.rules import ConsensusLockState
from src.consensus.vote import Vote, VoteType
from src.consensus.engine import ConsensusEngine


def test_vote_deduplication_and_single_vote_rule():
    chain_id = "test_chain"
    lock_state = ConsensusLockState()
    val_key = KeyPair()
    val_set = {val_key.public_key_hex}

    vote1 = Vote(
        validator=val_key.public_key_hex,
        height=1,
        round=0,
        phase=VoteType.PREVOTE,
        block_hash="hash_a",
    )
    vote1.sign(val_key, chain_id)

    # First vote accepted
    assert lock_state.add_received_vote(vote1, chain_id, val_set) is True

    # Duplicate vote rejected
    assert lock_state.add_received_vote(vote1, chain_id, val_set) is False

    # Conflicting vote from same validator at same (height, round, phase) rejected
    vote_conflict = Vote(
        validator=val_key.public_key_hex,
        height=1,
        round=0,
        phase=VoteType.PREVOTE,
        block_hash="hash_b",
    )
    vote_conflict.sign(val_key, chain_id)
    assert lock_state.add_received_vote(vote_conflict, chain_id, val_set) is False


def test_quorum_calculation():
    # 8 nodes: n = 8 -> f = (8 - 1) // 3 = 2 -> quorum = 2*2 + 1 = 5
    validators = [KeyPair() for _ in range(8)]
    val_keys = [k.public_key_hex for k in validators]
    chain_id = "test_chain"

    engine = ConsensusEngine("node0", validators[0], chain_id, val_keys)
    assert engine.f == 2
    assert engine.quorum_size == 5

    # Submit 4 prevotes (not enough)
    for i in range(4):
        v = Vote(validators[i].public_key_hex, 1, 0, VoteType.PREVOTE, "block_hash_1")
        v.sign(validators[i], chain_id)
        engine.lock_state.add_received_vote(v, chain_id, set(val_keys))

    assert engine.check_prevote_quorum(1, 0) is None

    # 5th prevote reaches quorum
    v5 = Vote(validators[4].public_key_hex, 1, 0, VoteType.PREVOTE, "block_hash_1")
    v5.sign(validators[4], chain_id)
    engine.lock_state.add_received_vote(v5, chain_id, set(val_keys))
    assert engine.check_prevote_quorum(1, 0) == "block_hash_1"
