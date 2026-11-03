"""
Unit tests for state execution, ownership verification, and replay protection.
"""
import pytest
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
