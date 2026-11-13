"""
Full validator node connecting cryptography, state execution, consensus, and network.
"""
from typing import List, Dict
from .crypto.identity import KeyPair
from .execution.state import State
from .execution.block import Block, BlockHeader
from .execution.transaction import Transaction
from .consensus.engine import ConsensusEngine
from .consensus.vote import Vote
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
        if not self.consensus.is_current_proposer():
            raise ValueError("This validator is not the proposer for the current round.")

        temp_state = self.state.copy()
        valid_txs = []
        for tx in self.pending_transactions:
            if temp_state.apply_transaction(tx, self.chain_id):
                valid_txs.append(tx)

        block = Block(
            header=BlockHeader(
                parent_hash=parent_hash,
                height=self.consensus.height,
                round=self.consensus.round,
                state_root=temp_state.state_root,
                proposer=self.public_key_hex,
                transactions_root="",
            ),
            transactions=valid_txs,
        )
        block.header.transactions_root = block.transactions_root
        block.header.sign(self.key_pair, self.chain_id)
        return block

    def add_pending_transaction(self, tx: Transaction) -> bool:
        """Validate and add a transaction once to the local mempool."""
        if not tx.is_valid(self.chain_id):
            return False
        if any(existing.tx_hash == tx.tx_hash for existing in self.pending_transactions):
            return False

        candidate_state = self.state.copy()
        for pending in self.pending_transactions:
            candidate_state.apply_transaction(pending, self.chain_id)
        if not candidate_state.apply_transaction(tx, self.chain_id):
            return False

        self.pending_transactions.append(tx)
        return True

    def receive_vote(self, vote: Vote) -> bool:
        """Validate and ingest vote from peer."""
        return self.consensus.add_received_vote(vote)

    def validate_proposal_header(
        self, header: BlockHeader, require_current_round: bool = True
    ) -> bool:
        """Validate proposal context and signature before asking for its body."""
        if header.height != self.consensus.height or header.round < 0:
            return False
        if require_current_round and header.round != self.consensus.round:
            return False
        if not require_current_round and header.round > self.consensus.round:
            return False

        expected_parent = (
            self.finalized_blocks[-1].block_hash if self.finalized_blocks else "0" * 64
        )
        if header.parent_hash != expected_parent:
            return False
        if header.proposer not in self.validator_keys:
            return False
        if header.proposer != self.consensus.get_proposer(header.height, header.round):
            return False
        if not header.is_valid_signature(self.chain_id):
            return False
        return True

    def validate_proposal_block(self, block: Block, require_current_round: bool = True) -> bool:
        """Check a proposal's context, signature, body commitment, and execution result."""
        header = block.header
        if not self.validate_proposal_header(header, require_current_round):
            return False
        if header.transactions_root != block.transactions_root:
            return False

        candidate_state = self.state.copy()
        if not candidate_state.apply_block_transactions(block.transactions, self.chain_id):
            return False
        return candidate_state.state_root == header.state_root

    def create_prevote_for_block(self, block: Block) -> Vote | None:
        """Validate and store a proposal before signing a PREVOTE for it."""
        if not self.validate_proposal_block(block):
            return None
        self.received_blocks[block.block_hash] = block
        return self.consensus.create_prevote(block.block_hash)

    def finalize_block(self, block: Block) -> bool:
        """Validate a committed block before updating state and advancing height."""
        header = block.header
        if not self.validate_proposal_block(block, require_current_round=False):
            return False
        if self.consensus.check_precommit_quorum(header.height, header.round) != block.block_hash:
            return False

        if not self.state.apply_block_transactions(block.transactions, self.chain_id):
            return False

        self.finalized_blocks.append(block)
        # Remove applied transactions
        applied_hashes = {tx.tx_hash for tx in block.transactions}
        self.pending_transactions = [
            tx for tx in self.pending_transactions if tx.tx_hash not in applied_hashes
        ]
        self.consensus.advance_to_next_height()
        return True
