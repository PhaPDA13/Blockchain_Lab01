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


def test_mutating_submitted_or_returned_vote_does_not_change_consensus_state():
    chain_id = "test_chain"
    lock_state = ConsensusLockState()
    val_key = KeyPair()
    vote = Vote(val_key.public_key_hex, 1, 0, VoteType.PREVOTE, "block_a")
    vote.sign(val_key, chain_id)
    assert lock_state.add_received_vote(vote, chain_id, {val_key.public_key_hex})

    vote.block_hash = "block_b"
    returned = lock_state.get_votes_for_phase(1, 0, VoteType.PREVOTE)
    returned[val_key.public_key_hex].block_hash = "block_c"

    stored = lock_state.get_votes_for_phase(1, 0, VoteType.PREVOTE)
    assert stored[val_key.public_key_hex].block_hash == "block_a"


def test_quorum_calculation():
    # 10 nodes: n = 3f + 1, f = 3, quorum = 2f + 1 = 7.
    validators = [KeyPair() for _ in range(10)]
    val_keys = [k.public_key_hex for k in validators]
    chain_id = "test_chain"

    engine = ConsensusEngine("node0", validators[0], chain_id, val_keys)
    assert engine.f == 3
    assert engine.quorum_size == 7

    # Submit 6 prevotes (not enough)
    for i in range(6):
        v = Vote(validators[i].public_key_hex, 1, 0, VoteType.PREVOTE, "block_hash_1")
        v.sign(validators[i], chain_id)
        engine.lock_state.add_received_vote(v, chain_id, set(val_keys))

    assert engine.check_prevote_quorum(1, 0) is None

    # 7th prevote reaches quorum
    v7 = Vote(validators[6].public_key_hex, 1, 0, VoteType.PREVOTE, "block_hash_1")
    v7.sign(validators[6], chain_id)
    engine.lock_state.add_received_vote(v7, chain_id, set(val_keys))
    assert engine.check_prevote_quorum(1, 0) == "block_hash_1"


def test_validator_count_must_follow_n_equals_three_f_plus_one():
    # Configurable n >= 8 is supported with safe BFT quorum floor(2n/3) + 1;
    # n < 4 (where f = 0) is rejected.
    validators_8 = [KeyPair() for _ in range(8)]
    engine_8 = ConsensusEngine(
        "node0",
        validators_8[0],
        "test_chain",
        [key.public_key_hex for key in validators_8],
    )
    assert engine_8.f == 2
    assert engine_8.quorum_size == 6
    assert 2 * engine_8.quorum_size - engine_8.n >= engine_8.f + 1

    validators_3 = [KeyPair() for _ in range(3)]
    with pytest.raises(ValueError, match="at least 4"):
        ConsensusEngine(
            "node0",
            validators_3[0],
            "test_chain",
            [key.public_key_hex for key in validators_3],
        )

    # Rule 6: Vote signing and validation reject invalid height, round, or phase
    bad_vote = Vote(validators_8[0].public_key_hex, 0, 0, VoteType.PREVOTE, "h")
    with pytest.raises(ValueError):
        bad_vote.sign(validators_8[0], "test_chain")


def test_precommit_requires_prevote_quorum():
    validators = [KeyPair() for _ in range(10)]
    val_keys = [key.public_key_hex for key in validators]
    engine = ConsensusEngine("node0", validators[0], "test_chain", val_keys)

    assert engine.create_precommit("block_hash_1") is None

    for key in validators[:7]:
        vote = Vote(key.public_key_hex, 1, 0, VoteType.PREVOTE, "block_hash_1")
        vote.sign(key, "test_chain")
        assert engine.add_received_vote(vote) is True

    # Rule 4: Prevote quorum locks block_hash_1 at round 0
    assert engine.lock_state.locked_block_hash == "block_hash_1"
    assert engine.lock_state.locked_round == 0

    precommit = engine.create_precommit("block_hash_1")
    assert precommit is not None

    # Rule 5: In round 1, validator locked on block_hash_1 cannot prevote block_hash_2
    # without observing a prevote quorum for block_hash_2 in a round > locked_round
    engine.advance_to_next_round()
    assert engine.create_prevote("block_hash_2") is None
    assert engine.create_prevote("block_hash_1") is not None

    # Observing a prevote quorum for block_hash_2 in round 1 unlocks/relocks to block_hash_2
    for key in validators[1:8]:
        vote_r1 = Vote(key.public_key_hex, 1, 1, VoteType.PREVOTE, "block_hash_2")
        vote_r1.sign(key, "test_chain")
        assert engine.add_received_vote(vote_r1) is True
    assert engine.lock_state.locked_block_hash == "block_hash_2"
    assert engine.lock_state.locked_round == 1

    engine.advance_to_next_round()
    assert engine.create_prevote("block_hash_2") is not None


def test_local_votes_count_toward_quorum():
    validators = [KeyPair() for _ in range(10)]
    val_keys = [key.public_key_hex for key in validators]
    engine = ConsensusEngine("node0", validators[0], "test_chain", val_keys)

    prevote = engine.create_prevote("block_hash_1")
    assert prevote is not None
    assert len(engine.lock_state.get_votes_for_phase(1, 0, VoteType.PREVOTE)) == 1

    for key in validators[1:7]:
        vote = Vote(key.public_key_hex, 1, 0, VoteType.PREVOTE, "block_hash_1")
        vote.sign(key, "test_chain")
        assert engine.add_received_vote(vote) is True
    assert engine.check_prevote_quorum(1, 0) == "block_hash_1"

    precommit = engine.create_precommit("block_hash_1")
    assert precommit is not None
    for key in validators[1:7]:
        vote = Vote(key.public_key_hex, 1, 0, VoteType.PRECOMMIT, "block_hash_1")
        vote.sign(key, "test_chain")
        assert engine.add_received_vote(vote) is True
    assert engine.check_precommit_quorum(1, 0) == "block_hash_1"
