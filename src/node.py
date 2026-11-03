"""
Full validator node connecting cryptography, state execution, consensus, and network.
"""
from typing import List, Dict, Optional, Set
from .crypto.identity import KeyPair
from .execution.state import State
from .execution.block import Block, BlockHeader
from .execution.transaction import Transaction
from .consensus.engine import ConsensusEngine
from .consensus.vote import Vote, VoteType
from .network.message import NetworkMessage, MessageType
from .network.logger import NetworkLogger


class Node:
    """Represents a blockchain validator node."""

    def __init__(
        self,
        node_id: str,
        key_pair: KeyPair,
        chain_id: str,
        validator_keys: List[str],
        is_byzantine: bool = False,
        byzantine_type: str = "none",  # silent, equivocate, invalid_block
    ):
        self.node_id = node_id
        self.key_pair = key_pair
        self.chain_id = chain_id
        self.validator_keys = validator_keys
        self.is_byzantine = is_byzantine
        self.byzantine_type = byzantine_type

        # Consensus and execution components
        self.consensus = ConsensusEngine(
            node_id=node_id,
            key_pair=key_pair,
            chain_id=chain_id,
            validators=validator_keys,
        )
        self.state = State()
        self.finalized_blocks: List[Block] = []

        # Local views and buffers
        self.pending_transactions: List[Transaction] = []
        self.received_headers: Dict[str, BlockHeader] = {}
        self.received_blocks: Dict[str, Block] = {}

        # Node event logger
        self.logger = NetworkLogger(node_id=node_id)

    @property
    def public_key_hex(self) -> str:
        return self.key_pair.public_key_hex

    @property
    def latest_state_root(self) -> str:
        return self.state.state_root

    def create_proposal_block(self, parent_hash: str) -> Block:
        """Proposer creates candidate block committing to post-execution state root."""
        temp_state = self.state.copy()
        valid_txs = []
        for tx in self.pending_transactions:
            if temp_state.apply_transaction(tx, self.chain_id):
                valid_txs.append(tx)

        header = BlockHeader(
            parent_hash=parent_hash,
            height=self.consensus.height,
            round=self.consensus.round,
            state_root=temp_state.state_root,
            proposer=self.public_key_hex,
        )
        header.sign(self.key_pair, self.chain_id)
        return Block(header=header, transactions=valid_txs)

    def receive_vote(self, vote: Vote) -> bool:
        """Validate and ingest vote from peer."""
        return self.consensus.lock_state.add_received_vote(
            vote=vote,
            chain_id=self.chain_id,
            validator_set=set(self.validator_keys),
        )

    def finalize_block(self, block: Block):
        """Finalize block, update state, and advance height."""
        self.state.apply_block_transactions(block.transactions, self.chain_id)
        self.finalized_blocks.append(block)
        # Remove applied transactions
        applied_hashes = {tx.tx_hash for tx in block.transactions}
        self.pending_transactions = [
            tx for tx in self.pending_transactions if tx.tx_hash not in applied_hashes
        ]
        self.consensus.advance_to_next_height()
