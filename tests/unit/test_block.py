"""Unit tests for block proposal validation guards."""
from src.crypto.identity import KeyPair
from src.execution.transaction import Transaction
from src.node import Node


def make_valid_proposal():
    chain_id = "block_validation_test"
    key_pairs = [KeyPair() for _ in range(10)]
    validator_keys = [key.public_key_hex for key in key_pairs]
    # At height 1, round 0, sorted validator index 1 is the proposer.
    proposer_key = sorted(key_pairs, key=lambda key: key.public_key_hex)[1]
    proposer = Node(
        "proposer",
        proposer_key,
        chain_id,
        validator_keys,
    )
    tx = Transaction(
        sender=key_pairs[0].public_key_hex,
        key=f"{key_pairs[0].public_key_hex}/message",
        value="hello",
        nonce=0,
    )
    tx.sign(key_pairs[0], chain_id)
    assert proposer.add_pending_transaction(tx)
    block = proposer.create_proposal_block("0" * 64)
    return chain_id, key_pairs, validator_keys, proposer_key, proposer, block


def test_valid_block_proposal_is_accepted():
    _, _, _, _, proposer, block = make_valid_proposal()
    assert proposer.validate_proposal_block(block) is True


def test_block_with_invalid_header_signature_is_rejected():
    _, _, _, _, proposer, block = make_valid_proposal()
    block.header.signature = "00"
    assert proposer.validate_proposal_block(block) is False


def test_block_with_wrong_parent_is_rejected_even_when_resigned():
    chain_id, _, _, proposer_key, proposer, block = make_valid_proposal()
    block.header.parent_hash = "1" * 64
    block.header.sign(proposer_key, chain_id)
    assert proposer.validate_proposal_block(block) is False


def test_block_with_wrong_proposer_is_rejected_even_when_resigned():
    chain_id, key_pairs, _, _, proposer, block = make_valid_proposal()
    wrong_key = next(
        key
        for key in key_pairs
        if key.public_key_hex != block.header.proposer
    )
    block.header.proposer = wrong_key.public_key_hex
    block.header.sign(wrong_key, chain_id)
    assert proposer.validate_proposal_block(block) is False


def test_block_with_wrong_round_is_rejected():
    _, _, _, _, proposer, block = make_valid_proposal()
    block.header.round = 1
    assert proposer.validate_proposal_block(block) is False


def test_block_with_wrong_transactions_root_is_rejected_even_when_resigned():
    chain_id, _, _, proposer_key, proposer, block = make_valid_proposal()
    block.header.transactions_root = "a" * 64
    block.header.sign(proposer_key, chain_id)
    assert proposer.validate_proposal_block(block) is False


def test_block_with_wrong_state_root_is_rejected_even_when_resigned():
    chain_id, _, _, proposer_key, proposer, block = make_valid_proposal()
    block.header.state_root = "a" * 64
    block.header.sign(proposer_key, chain_id)
    assert proposer.validate_proposal_block(block) is False
