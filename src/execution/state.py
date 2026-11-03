"""
Deterministic shared key-value state and state transitions.
"""
from typing import Dict, Set, Optional, List
from .transaction import Transaction
from ..crypto.hashing import compute_state_root


class State:
    """Deterministic key-value application state."""

    def __init__(self, initial_records: Optional[Dict[str, str]] = None):
        self._records: Dict[str, str] = dict(initial_records) if initial_records else {}
        self._sender_nonces: Dict[str, int] = {}
        self._executed_tx_hashes: Set[str] = set()

    def copy(self) -> "State":
        """Create a deep copy of the state."""
        new_state = State(self._records)
        new_state._sender_nonces = dict(self._sender_nonces)
        new_state._executed_tx_hashes = set(self._executed_tx_hashes)
        return new_state

    @property
    def records(self) -> Dict[str, str]:
        """Read-only view of current state records."""
        return dict(self._records)

    @property
    def state_root(self) -> str:
        """Deterministic commitment hash of the current state."""
        return compute_state_root(self._records)

    def apply_transaction(self, tx: Transaction, chain_id: str) -> bool:
        """
        Validate and deterministically execute a single transaction.
        Enforces replay protection and sender nonce sequencing.
        """
        # Validate tx structure & signature
        if not tx.is_valid(chain_id):
            return False

        # Anti-replay: hash uniqueness
        if tx.tx_hash in self._executed_tx_hashes:
            return False

        # Nonce ordering check
        expected_nonce = self._sender_nonces.get(tx.sender, 0)
        if tx.nonce != expected_nonce:
            return False

        # Apply state transition
        self._records[tx.key] = tx.value
        self._sender_nonces[tx.sender] = expected_nonce + 1
        self._executed_tx_hashes.add(tx.tx_hash)
        return True

    def apply_block_transactions(self, transactions: List[Transaction], chain_id: str) -> bool:
        """Apply an ordered list of transactions. All or nothing semantics."""
        snapshot = self.copy()
        for tx in transactions:
            if not snapshot.apply_transaction(tx, chain_id):
                return False
        self._records = snapshot._records
        self._sender_nonces = snapshot._sender_nonces
        self._executed_tx_hashes = snapshot._executed_tx_hashes
        return True
