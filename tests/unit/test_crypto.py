"""
Unit tests for cryptographic verification, domain separation, and deterministic encoding.
"""
import pytest
from src.crypto.identity import KeyPair, verify_signature
from src.crypto.encoding import canonical_encode
from src.crypto.hashing import hash_data, compute_state_root


def test_deterministic_encoding():
    data1 = {"b": 2, "a": 1, "c": [3, 2, 1]}
    data2 = {"a": 1, "c": [3, 2, 1], "b": 2}
    assert canonical_encode(data1) == canonical_encode(data2)
    assert hash_data(data1) == hash_data(data2)


def test_signature_and_domain_separation():
    chain_id = "test_chain"
    key_pair = KeyPair()
    msg = {"action": "transfer", "amount": 100}

    # Sign under TX domain
    sig_tx = key_pair.sign(msg, f"TX:{chain_id}")

    # Valid under TX domain
    assert verify_signature(key_pair.public_key_hex, msg, sig_tx, f"TX:{chain_id}") is True

    # Invalid under HEADER or VOTE domain (domain separation requirement)
    assert verify_signature(key_pair.public_key_hex, msg, sig_tx, f"HEADER:{chain_id}") is False
    assert verify_signature(key_pair.public_key_hex, msg, sig_tx, f"VOTE:{chain_id}") is False
    assert verify_signature(key_pair.public_key_hex, msg, sig_tx, "TX:other_chain") is False


def test_state_root_commitment():
    state1 = {"Alice/balance": "100", "Bob/balance": "50"}
    state2 = {"Bob/balance": "50", "Alice/balance": "100"}
    assert compute_state_root(state1) == compute_state_root(state2)
