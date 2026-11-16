"""End-to-end Lab scenarios driven through NetworkRunner and NetworkSimulator."""
from dataclasses import asdict

from src.consensus.vote import Vote, VoteType
from src.crypto.identity import KeyPair
from src.execution.transaction import Transaction
from src.network.message import MessageType, NetworkMessage
from src.network.runner import NetworkRunner
from src.network.simulator import NetworkSimulator
from src.node import Node


def setup_cluster(num_nodes=10, seed=42):
    chain_id = "lab01_test_chain"
    key_pairs = [KeyPair.from_seed(bytes([i + seed % 200] * 32)) for i in range(num_nodes)]
    validator_keys = [key_pair.public_key_hex for key_pair in key_pairs]
    nodes = [
        Node(f"node_{index}", key_pairs[index], chain_id, validator_keys)
        for index in range(num_nodes)
    ]
    return chain_id, nodes, key_pairs


def setup_runner(
    seed=42,
    *,
    drop_rate=0.0,
    duplicate_rate=0.0,
    stabilization_time=1000,
    max_delay=2,
    timeout=8,
    auto_propose=True,
):
    chain_id, nodes, key_pairs = setup_cluster(seed=seed)
    simulator = NetworkSimulator(
        [node.node_id for node in nodes],
        seed=seed + 500,
        drop_rate=drop_rate,
        duplicate_rate=duplicate_rate,
        min_delay=1,
        max_delay=max_delay,
        stabilization_time=stabilization_time,
        delta_bound=2,
        max_outbound_rate=50,
        rate_window_ticks=1000,
    )
    runner = NetworkRunner(
        nodes,
        simulator,
        round_timeout_ticks=timeout,
        retransmit_interval_ticks=1000,
        auto_propose=auto_propose,
    )
    return chain_id, nodes, key_pairs, runner


def make_transaction(key_pair, chain_id, value="active", nonce=0):
    tx = Transaction(
        sender=key_pair.public_key_hex,
        key=f"{key_pair.public_key_hex}/status",
        value=value,
        nonce=nonce,
    )
    tx.sign(key_pair, chain_id)
    return tx


def test_t1_normal_run_no_faults():
    """T1: All correct nodes finalize the same block and state through the network."""
    chain_id, nodes, key_pairs, runner = setup_runner()
    proposer = next(
        node
        for node in nodes
        if node.public_key_hex == node.consensus.get_proposer(height=1, round=0)
    )
    tx = make_transaction(key_pairs[0], chain_id)
    assert runner.submit_transaction(tx, proposer.node_id) is True

    assert runner.run_until_finalized(1, max_ticks=100) is True
    finalized_hashes = {node.finalized_blocks[0].block_hash for node in nodes}
    state_roots = {node.latest_state_root for node in nodes}
    assert len(finalized_hashes) == 1
    assert len(state_roots) == 1
    assert runner.is_safe() is True

    receiver = next(node for node in nodes if node is not proposer)
    events = [entry["type"] for entry in receiver.logger.entries]
    assert events.index("header_accepted") < events.index("body_accepted")
    assert "prevote" in events
    assert "precommit" in events


def test_t2_duplicate_and_reordered_network_messages():
    """T2: Duplicate and reordered delivery does not double-count votes or split finality."""
    chain_id, nodes, key_pairs, runner = setup_runner(
        seed=11, duplicate_rate=0.25, max_delay=4, timeout=30
    )
    proposer = next(
        node
        for node in nodes
        if node.public_key_hex == node.consensus.get_proposer(height=1, round=0)
    )
    assert runner.submit_transaction(make_transaction(key_pairs[0], chain_id), proposer.node_id)

    assert runner.run_until_finalized(1, max_ticks=150) is True
    assert any(entry["type"] == "duplicate" for entry in runner.simulator.logger.entries)
    assert any(
        entry["type"] == "vote_rejected"
        for node in nodes
        for entry in node.logger.entries
    )
    assert len({node.finalized_blocks[0].block_hash for node in nodes}) == 1
    assert runner.is_safe() is True


def test_t3_invalid_signature_wrong_domain_is_rejected_and_logged():
    """T3: An invalidly signed transaction is rejected at network ingress and logged."""
    chain_id, nodes, _, runner = setup_runner(auto_propose=False)
    tx = Transaction(
        sender=nodes[0].public_key_hex,
        key=f"{nodes[0].public_key_hex}/status",
        value="forged",
        nonce=0,
    )
    tx.signature = nodes[0].key_pair.sign(tx.payload_dict(), "TX:wrong_domain")
    receiver = nodes[1]
    runner.simulator.send_message(
        NetworkMessage(
            MessageType.TX,
            nodes[0].node_id,
            receiver.node_id,
            1,
            {"transaction": asdict(tx)},
        )
    )
    forged_vote = Vote(
        nodes[0].public_key_hex,
        1,
        0,
        VoteType.PREVOTE,
        "forged-block",
    )
    forged_vote.signature = nodes[0].key_pair.sign(
        forged_vote.payload_dict(), "VOTE:wrong_domain"
    )
    runner.simulator.send_message(
        NetworkMessage(
            MessageType.VOTE,
            nodes[0].node_id,
            receiver.node_id,
            1,
            runner._vote_payload(forged_vote),
        )
    )
    runner.run_for(3)

    assert receiver.pending_transactions == []
    assert any(
        entry["type"] == "message_rejected"
        and entry["details"]["reason"] == "invalid_signature_or_ownership"
        for entry in receiver.logger.entries
    )
    assert any(
        entry["type"] == "vote_rejected"
        and entry["details"]["reason"] == "invalid_signature_or_domain"
        for entry in receiver.logger.entries
    )


def test_t4_replayed_transaction_is_applied_at_most_once():
    """T4: A transaction replay over the network cannot change finalized state twice."""
    chain_id, nodes, key_pairs, runner = setup_runner()
    proposer = next(
        node
        for node in nodes
        if node.public_key_hex == node.consensus.get_proposer(height=1, round=0)
    )
    tx = make_transaction(key_pairs[0], chain_id, value="once")
    assert runner.submit_transaction(tx, proposer.node_id) is True
    assert runner.run_until_finalized(1, max_ticks=100) is True
    ingress = nodes[0]
    root_before = ingress.latest_state_root
    assert ingress.state.records[tx.key] == "once"

    replay_receiver = nodes[1]
    runner.simulator.send_message(
        NetworkMessage(
            MessageType.TX,
            nodes[0].node_id,
            replay_receiver.node_id,
            2,
            {"transaction": asdict(tx)},
        )
    )
    runner.run_for(3)
    assert replay_receiver.latest_state_root == root_before
    assert replay_receiver.state.records[tx.key] == "once"
    assert any(
        entry["type"] == "message_rejected"
        and entry["details"]["reason"] == "duplicate_replay_or_nonce"
        for entry in replay_receiver.logger.entries
    )


def test_t5_drop_and_delay_preserve_safety_and_recover_after_stabilization():
    """T5: Faulty early delivery causes no split finality; the stable network recovers."""
    chain_id, nodes, key_pairs, runner = setup_runner(
        seed=23,
        drop_rate=0.4,
        stabilization_time=16,
        max_delay=4,
        timeout=8,
    )
    proposer = next(
        node
        for node in nodes
        if node.public_key_hex == node.consensus.get_proposer(height=1, round=0)
    )
    assert runner.submit_transaction(make_transaction(key_pairs[0], chain_id), proposer.node_id)

    assert runner.run_until_finalized(1, max_ticks=300) is True
    assert any(entry["type"] == "drop" for entry in runner.simulator.logger.entries)
    assert any(entry["type"] == "delay" for entry in runner.simulator.logger.entries)
    assert runner.is_safe() is True
    assert len({node.finalized_blocks[0].block_hash for node in nodes}) == 1


def test_t6_silent_proposer_times_out_and_next_round_finalizes():
    """T6: A silent round-zero proposer times out and round one continues."""
    chain_id, nodes, key_pairs, runner = setup_runner(seed=31, timeout=6)
    round_zero_proposer = next(
        node
        for node in nodes
        if node.public_key_hex == node.consensus.get_proposer(height=1, round=0)
    )
    runner.silent_nodes.add(round_zero_proposer.node_id)
    round_one_proposer_key = nodes[0].consensus.get_proposer(height=1, round=1)
    round_one_proposer = next(
        node for node in nodes if node.public_key_hex == round_one_proposer_key
    )
    assert runner.submit_transaction(make_transaction(key_pairs[0], chain_id), round_one_proposer.node_id)

    assert runner.run_until_finalized(1, max_ticks=100) is True
    assert all(node.finalized_blocks[0].header.round == 1 for node in nodes)
    assert any(
        entry["type"] == "round_timeout"
        for node in nodes
        for entry in node.logger.entries
    )


def test_t7_byzantine_equivocation_cannot_form_a_false_quorum():
    """T7: Up to f=3 equivocal validators cannot form a false quorum."""
    chain_id, nodes, key_pairs, runner = setup_runner(
        seed=47, timeout=100, auto_propose=False, max_delay=2
    )
    honest_nodes = nodes[3:]
    for byzantine_index in range(3):
        byzantine = nodes[byzantine_index]
        for block_hash in ("block_A", "block_B"):
            vote = Vote(
                byzantine.public_key_hex,
                1,
                0,
                VoteType.PREVOTE,
                block_hash,
            )
            vote.sign(key_pairs[byzantine_index], chain_id)
            for receiver in honest_nodes:
                runner.simulator.send_message(
                    NetworkMessage(
                        MessageType.VOTE,
                        byzantine.node_id,
                        receiver.node_id,
                        1,
                        runner._vote_payload(vote),
                    )
                )

    runner.run_for(4)
    for node in honest_nodes:
        votes = node.consensus.lock_state.get_votes_for_phase(1, 0, VoteType.PREVOTE)
        assert len(votes) == 3
        assert node.consensus.check_prevote_quorum(1, 0) is None
        assert not node.finalized_blocks
        assert sum(entry["type"] == "vote_rejected" for entry in node.logger.entries) == 3


def test_t8_same_seed_reproduces_final_state_and_all_logs():
    """T8: Identical seed and inputs reproduce state, node logs, and transport logs."""
    def run_once(seed):
        chain_id, nodes, key_pairs, runner = setup_runner(seed=seed)
        proposer = next(
            node
            for node in nodes
            if node.public_key_hex == node.consensus.get_proposer(height=1, round=0)
        )
        assert runner.submit_transaction(
            make_transaction(key_pairs[0], chain_id), proposer.node_id
        )
        assert runner.run_until_finalized(1, max_ticks=100) is True
        return (
            tuple(node.latest_state_root for node in nodes),
            tuple(
                tuple(block.block_hash for block in node.finalized_blocks)
                for node in nodes
            ),
            tuple(node.logger.export_canonical_bytes() for node in nodes),
            runner.simulator.logger.export_canonical_bytes(),
        )

    assert run_once(999) == run_once(999)


def test_new_height_round_timer_starts_at_current_simulation_time():
    _, nodes, _, runner = setup_runner(timeout=8)
    for node in nodes:
        node.consensus.advance_to_next_height()
    runner.simulator.current_time = 100

    runner._advance_timed_out_rounds()

    assert all(node.consensus.round == 0 for node in nodes)


def test_from_config_reads_timeout_round_ticks():
    _, nodes, _ = setup_cluster()
    runner = NetworkRunner.from_config(
        nodes,
        {"num_nodes": 10, "timeout_round_ticks": 17},
    )

    assert runner.round_timeout_ticks == 17


def test_late_round_header_and_body_are_accepted_for_finalization_checks():
    _, nodes, _, runner = setup_runner()
    proposer = next(
        node
        for node in nodes
        if node.consensus.get_proposer(1, 0) == node.public_key_hex
    )
    receiver = next(node for node in nodes if node is not proposer)
    block = proposer.create_proposal_block("0" * 64)
    receiver.consensus.advance_to_next_round()

    runner._handle_message(
        NetworkMessage(
            MessageType.HEADER,
            proposer.node_id,
            receiver.node_id,
            1,
            {
                "block_hash": block.block_hash,
                "proposal_hash": block.header.header_hash,
                "header": asdict(block.header),
            },
        )
    )
    runner._handle_message(
        NetworkMessage(
            MessageType.BODY,
            proposer.node_id,
            receiver.node_id,
            1,
            {
                "block_hash": block.block_hash,
                "proposal_hash": block.header.header_hash,
                "transactions": [runner._transaction_payload(tx) for tx in block.transactions],
            },
        )
    )

    assert any(
        candidate.block_hash == block.block_hash and candidate.header.round == 0
        for candidate in receiver.received_blocks.values()
    )


def test_finality_certificate_catches_up_a_lagging_node():
    chain_id, nodes, key_pairs, runner = setup_runner()
    proposer = next(
        node
        for node in nodes
        if node.consensus.get_proposer(1, 0) == node.public_key_hex
    )
    receiver = next(node for node in nodes if node is not proposer)
    block = proposer.create_proposal_block("0" * 64)
    certificate = []
    for key_pair in key_pairs[:7]:
        vote = Vote(
            key_pair.public_key_hex,
            1,
            0,
            VoteType.PRECOMMIT,
            block.block_hash,
        )
        vote.sign(key_pair, chain_id)
        certificate.append(vote)

    runner._handle_message(
        NetworkMessage(
            MessageType.FINALIZED,
            proposer.node_id,
            receiver.node_id,
            1,
            runner._finalized_payload(block, certificate),
        )
    )

    assert receiver.consensus.height == 2
    assert receiver.finalized_blocks[0].block_hash == block.block_hash


def test_multi_height_recovery_after_early_message_faults():
    _, nodes, _, runner = setup_runner(
        seed=0,
        drop_rate=0.1,
        duplicate_rate=0.05,
        stabilization_time=20,
        max_delay=6,
        timeout=8,
    )

    assert runner.run_until_finalized(1, max_ticks=500)
    assert runner.run_until_finalized(2, max_ticks=2000)
    assert runner.is_safe()
    assert all(len(node.finalized_blocks) >= 2 for node in nodes)
