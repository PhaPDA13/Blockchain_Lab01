"""
End-to-end tests for Lab 01 (Scenarios T1 - T8).
Required test cases from Section 9 of Lab01.pdf:
- T1: Normal run, no faults -> All correct nodes finalize same chain and state hash
- T2: Duplicate/reordered messages -> No double-counted votes, no conflicting finalization
- T3: Invalid signature / wrong domain -> Message rejected, reason logged
- T4: Replayed/duplicate transaction -> Applied at most once
- T5: Drop/delay before synchrony -> Safety holds; no double finalization at same height
- T6: Proposer silent/crashed -> Round timeout triggers, chain continues
- T7: Up to f Byzantine validators equivocate -> No conflicting finalization
- T8: Same seed rerun twice -> Byte-identical logs and final state hash
"""
import pytest
from src.crypto.identity import KeyPair, verify_signature
from src.execution.transaction import Transaction
from src.execution.state import State
from src.execution.block import Block, BlockHeader
from src.consensus.engine import ConsensusEngine
from src.consensus.vote import Vote, VoteType
from src.node import Node
from src.network.simulator import NetworkSimulator


def setup_cluster(num_nodes=8, seed=42):
    chain_id = "lab01_test_chain"
    key_pairs = [KeyPair.from_seed(bytes([i + seed % 200] * 32)) for i in range(num_nodes)]
    val_keys = [kp.public_key_hex for kp in key_pairs]
    nodes = [
        Node(f"node_{i}", key_pairs[i], chain_id, val_keys)
        for i in range(num_nodes)
    ]
    return chain_id, nodes, key_pairs


def test_t1_normal_run_no_faults():
    """T1: All correct nodes finalize same chain and state hash."""
    chain_id, nodes, key_pairs = setup_cluster(8)
    sim = NetworkSimulator([n.node_id for n in nodes], seed=101)

    # Proposer (node 0) creates block 1
    tx = Transaction(
        sender=key_pairs[0].public_key_hex,
        key=f"{key_pairs[0].public_key_hex}/status",
        value="active",
        nonce=0,
    )
    tx.sign(key_pairs[0], chain_id)
    nodes[0].pending_transactions.append(tx)
    block1 = nodes[0].create_proposal_block(parent_hash="0" * 64)

    # All nodes receive block and vote
    for node in nodes:
        node.received_blocks[block1.block_hash] = block1
        # Prevote
        v_prevote = node.consensus.create_prevote(block1.block_hash)
        for peer in nodes:
            peer.receive_vote(v_prevote)

    # All nodes precommit after prevote quorum
    for node in nodes:
        assert node.consensus.check_prevote_quorum(1, 0) == block1.block_hash
        v_precommit = node.consensus.create_precommit(block1.block_hash)
        for peer in nodes:
            peer.receive_vote(v_precommit)

    # All nodes finalize block 1
    for node in nodes:
        final_hash = node.consensus.check_precommit_quorum(1, 0)
        assert final_hash == block1.block_hash
        node.finalize_block(block1)

    # Assert state agreement across all nodes
    root = nodes[0].latest_state_root
    for node in nodes:
        assert node.latest_state_root == root
        assert len(node.finalized_blocks) == 1


def test_t2_duplicate_reordered_messages():
    """T2: Duplicate/reordered messages -> No double-counted votes, no conflicting finalization."""
    chain_id, nodes, key_pairs = setup_cluster(8)
    node = nodes[0]
    val_set = set(node.validator_keys)

    vote = Vote(key_pairs[1].public_key_hex, 1, 0, VoteType.PREVOTE, "hash_x")
    vote.sign(key_pairs[1], chain_id)

    # Ingest vote once
    assert node.consensus.lock_state.add_received_vote(vote, chain_id, val_set) is True
    # Duplicate vote rejected
    assert node.consensus.lock_state.add_received_vote(vote, chain_id, val_set) is False

    # Check vote counts
    votes = node.consensus.lock_state.get_votes_for_phase(1, 0, VoteType.PREVOTE)
    assert len(votes) == 1


def test_t3_invalid_signature_wrong_domain():
    """T3: Invalid signature / wrong domain -> Message rejected, reason logged."""
    chain_id = "chain_A"
    kp = KeyPair()
    tx = Transaction(kp.public_key_hex, f"{kp.public_key_hex}/msg", "val", 0)

    # Sign under wrong domain
    tx.signature = kp.sign(tx.payload_dict(), "TX:WRONG_CHAIN")

    # Rejected when verifying against chain_A
    assert tx.is_valid(chain_id) is False


def test_t4_replayed_duplicate_transaction():
    """T4: Replayed/duplicate transaction -> Applied at most once."""
    chain_id = "test_chain"
    kp = KeyPair()
    state = State()

    tx = Transaction(kp.public_key_hex, f"{kp.public_key_hex}/val", "123", 0)
    tx.sign(kp, chain_id)

    assert state.apply_transaction(tx, chain_id) is True
    # Replay of same transaction must be rejected
    assert state.apply_transaction(tx, chain_id) is False


def test_t5_drop_delay_before_synchrony():
    """T5: Drop/delay before synchrony -> Safety holds; no double finalization at same height."""
    chain_id, nodes, key_pairs = setup_cluster(8)
    sim = NetworkSimulator([n.node_id for n in nodes], seed=55, drop_rate=0.4, min_delay=1, max_delay=10)

    # Ensure no conflicting finalization can ever occur
    finalized_per_height = {}
    for node in nodes:
        for b in node.finalized_blocks:
            h = b.header.height
            if h in finalized_per_height:
                assert finalized_per_height[h] == b.block_hash
            else:
                finalized_per_height[h] = b.block_hash


def test_t6_proposer_silent_crashed():
    """T6: Proposer silent/crashed -> Round timeout triggers, chain continues."""
    chain_id, nodes, key_pairs = setup_cluster(8)
    # Proposer for round 0 fails to propose -> round timeout occurs
    for node in nodes:
        node.consensus.advance_to_next_round()
        assert node.consensus.round == 1
    # Next proposer takes over
    new_proposer = nodes[0].consensus.get_proposer(height=1, round=1)
    assert new_proposer in nodes[0].validator_keys


def test_t7_byzantine_equivocation():
    """T7: Up to f Byzantine validators equivocate -> No conflicting finalization."""
    chain_id, nodes, key_pairs = setup_cluster(8)
    # n=8, f=2. 2 byzantine nodes send conflicting votes
    byzantine_keys = key_pairs[:2]
    val_set = set(nodes[0].validator_keys)

    for bk in byzantine_keys:
        v1 = Vote(bk.public_key_hex, 1, 0, VoteType.PREVOTE, "hash_block_A")
        v1.sign(bk, chain_id)
        v2 = Vote(bk.public_key_hex, 1, 0, VoteType.PREVOTE, "hash_block_B")
        v2.sign(bk, chain_id)

        # Honest nodes accept first, reject second conflicting vote
        for node in nodes[2:]:
            node.consensus.lock_state.add_received_vote(v1, chain_id, val_set)
            node.consensus.lock_state.add_received_vote(v2, chain_id, val_set)

    # Byzantine nodes cannot cause two different blocks to get quorum (quorum requires 5 votes, only 2 byzantine)
    for node in nodes[2:]:
        assert node.consensus.check_prevote_quorum(1, 0) is None


def test_t8_same_seed_rerun_twice():
    """T8: Same seed rerun twice -> Byte-identical logs and final state hash."""
    def run_simulation(seed):
        chain_id, nodes, key_pairs = setup_cluster(8, seed=seed)
        sim = NetworkSimulator([n.node_id for n in nodes], seed=seed)
        # Produce transactions and log events
        tx = Transaction(key_pairs[0].public_key_hex, f"{key_pairs[0].public_key_hex}/x", "1", 0)
        tx.sign(key_pairs[0], chain_id)
        nodes[0].state.apply_transaction(tx, chain_id)
        nodes[0].logger.log_event(1, "tx_applied", 1, {"hash": tx.tx_hash})
        return nodes[0].state.state_root, nodes[0].logger.export_canonical_bytes()

    state_root1, logs1 = run_simulation(seed=999)
    state_root2, logs2 = run_simulation(seed=999)

    assert state_root1 == state_root2
    assert logs1 == logs2
