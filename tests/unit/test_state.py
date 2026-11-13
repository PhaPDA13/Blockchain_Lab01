"""
Unit tests for state execution, ownership verification, and replay protection.
"""
from src.crypto.identity import KeyPair
from src.execution.transaction import Transaction
from src.execution.state import State


def test_transaction_ownership_and_execution():
    chain_id = "test_chain"
    alice_keys = KeyPair()
    bob_keys = KeyPair()

    state = State()

    # Valid transaction: Alice updates Alice/message
    tx1 = Transaction(
        sender=alice_keys.public_key_hex,
        key=f"{alice_keys.public_key_hex}/message",
        value="hello",
        nonce=0,
    )
    tx1.sign(alice_keys, chain_id)
    assert state.apply_transaction(tx1, chain_id) is True
    assert state.records[tx1.key] == "hello"

    # Invalid ownership: Bob attempts to update Alice's key
    tx_bad_owner = Transaction(
        sender=bob_keys.public_key_hex,
        key=f"{alice_keys.public_key_hex}/message",
        value="hacked",
        nonce=0,
    )
    tx_bad_owner.sign(bob_keys, chain_id)
    assert state.apply_transaction(tx_bad_owner, chain_id) is False

    # Anti-replay: Re-applying tx1 must fail
    assert state.apply_transaction(tx1, chain_id) is False


def test_nonce_ordering():
    chain_id = "test_chain"
    alice_keys = KeyPair()
    state = State()

    # Nonce 1 sent before nonce 0 must fail
    tx_nonce1 = Transaction(
        sender=alice_keys.public_key_hex,
        key=f"{alice_keys.public_key_hex}/balance",
        value="100",
        nonce=1,
    )
    tx_nonce1.sign(alice_keys, chain_id)
    assert state.apply_transaction(tx_nonce1, chain_id) is False


def test_state_root_commits_sender_nonce():
    chain_id = "test_chain"
    alice_keys = KeyPair()
    key = f"{alice_keys.public_key_hex}/status"
    state = State({key: "active"})
    root_before = state.state_root

    tx = Transaction(
        sender=alice_keys.public_key_hex,
        key=key,
        value="active",
        nonce=0,
    )
    tx.sign(alice_keys, chain_id)

    assert state.apply_transaction(tx, chain_id) is True
    assert state.records == {key: "active"}
    assert state.state_root != root_before
