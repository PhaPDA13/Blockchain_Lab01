"""Event loop joining validator nodes to the unreliable network simulator."""
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..consensus.vote import Vote, VoteType
from ..execution.block import Block, BlockHeader
from ..execution.transaction import Transaction
from ..node import Node
from .message import MessageType, NetworkMessage
from .simulator import NetworkSimulator


class NetworkRunner:
    """Drive proposals, framed block delivery, votes, timeouts, and finalization."""

    def __init__(
        self,
        nodes: List[Node],
        simulator: NetworkSimulator,
        round_timeout_ticks: int = 20,
        retransmit_interval_ticks: int = 5,
        auto_propose: bool = True,
    ):
        if not nodes:
            raise ValueError("At least one validator node is required.")
        if round_timeout_ticks < 1 or retransmit_interval_ticks < 1:
            raise ValueError("Timeout and retransmit intervals must be positive.")

        self.nodes = {node.node_id: node for node in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError("Validator node IDs must be unique.")
        if set(self.nodes) != set(simulator.node_ids):
            raise ValueError("Simulator nodes must match the validator node IDs.")

        validator_sets = {tuple(node.consensus.validators) for node in nodes}
        if len(validator_sets) != 1:
            raise ValueError("All nodes must use the same validator set.")

        self.simulator = simulator
        self.round_timeout_ticks = round_timeout_ticks
        self.retransmit_interval_ticks = retransmit_interval_ticks
        self.auto_propose = auto_propose
        self.silent_nodes: Set[str] = set()

        self._node_by_public_key = {
            node.public_key_hex: node.node_id for node in nodes
        }
        self._proposed_rounds: Set[Tuple[str, int, int]] = set()
        self._blocks: Dict[str, Block] = {}
        self._body_requested: Set[Tuple[str, str]] = set()
        self._round_started: Dict[Tuple[str, int, int], int] = {}
        self._vote_history: Dict[Tuple[str, int, int, str], Dict[str, object]] = {}
        self._last_vote_broadcast: Dict[Tuple[str, int, int, str], int] = {}
        self._header_history: Dict[Tuple[str, int, int], Dict[str, object]] = {}
        self._last_header_broadcast: Dict[Tuple[str, int, int], int] = {}
        self._finalized_history: Dict[int, Tuple[str, Dict[str, object]]] = {}
        self._last_finalized_broadcast: Dict[int, int] = {}
        self._pending_finalized: Dict[str, Dict[int, Tuple[str, Dict[str, object]]]] = {}
        self._target_height: Optional[int] = None
        self.finalized_by_height: Dict[int, Dict[str, str]] = {}
        self.safety_violations: List[Tuple[int, str, str]] = []

        for node_id in sorted(self.nodes):
            self.simulator.register_handler(node_id, self._handle_message)

    @classmethod
    def from_config(cls, nodes: List[Node], config: Dict[str, object]) -> "NetworkRunner":
        """Build a runner and simulator from config/default_config.json values."""
        expected_nodes = int(config.get("num_nodes", len(nodes)))
        if (
            expected_nodes != len(nodes)
            or expected_nodes < 8
            or (expected_nodes - 1) % 3 != 0
        ):
            raise ValueError(
                "Config must match supplied nodes and satisfy n = 3f + 1 with n >= 8."
            )
        fault_budget = int(config.get("max_byzantine_faults", 0))
        if fault_budget < 0 or fault_budget > (expected_nodes - 1) // 3:
            raise ValueError("max_byzantine_faults exceeds the validator-set fault bound.")

        node_ids = [node.node_id for node in nodes]
        simulator = NetworkSimulator(
            node_ids,
            seed=int(config.get("random_seed", 42)),
            drop_rate=float(config.get("drop_rate", 0.0)),
            duplicate_rate=float(config.get("duplicate_rate", 0.0)),
            min_delay=int(config.get("min_delay_ticks", 1)),
            max_delay=int(config.get("max_delay_ticks", 5)),
            stabilization_time=int(config.get("stabilization_time_ticks", 1000)),
            delta_bound=int(config.get("delta_bound_ticks", 2)),
            max_outbound_rate=int(config.get("max_outbound_rate", 50)),
            rate_window_ticks=int(config.get("rate_window_ticks", 1000)),
        )
        return cls(
            nodes,
            simulator,
            round_timeout_ticks=int(
                config.get("timeout_round_ticks", config.get("timeout_round_ms", 1000))
            ),
            retransmit_interval_ticks=int(config.get("retransmit_interval_ticks", 1000)),
        )

    def submit_transaction(self, tx: Transaction, ingress_node_id: str) -> bool:
        """Submit a signed transaction to one node and gossip it to its peers."""
        node = self.nodes[ingress_node_id]
        accepted = node.add_pending_transaction(tx)
        node.logger.log_event(
            self.simulator.current_time,
            "tx_accepted" if accepted else "tx_rejected",
            node.consensus.height,
            {"hash": tx.tx_hash, "source": "client"},
        )
        if accepted:
            self._broadcast(
                ingress_node_id,
                MessageType.TX,
                node.consensus.height,
                {"transaction": self._transaction_payload(tx)},
            )
        return accepted

    def step(self) -> int:
        """Advance simulated time and run handlers, timeouts, and consensus actions."""
        delivered = self.simulator.step()
        self._drive_consensus()
        self._advance_timed_out_rounds()
        self._drive_consensus()
        self._retransmit()
        return delivered

    def run_until_finalized(self, height: int, max_ticks: int = 10_000) -> bool:
        """Run until every validator finalizes ``height`` or the tick bound expires."""
        if height < 1 or max_ticks < 0:
            raise ValueError("height must be positive and max_ticks non-negative.")
        self._target_height = height + 1
        self._drive_consensus()
        for _ in range(max_ticks):
            if all(node.consensus.height > height for node in self.nodes.values()):
                return self.is_safe()
            self.step()
        if all(node.consensus.height > height for node in self.nodes.values()):
            return self.is_safe()
        return all(node.consensus.height > height for node in self.nodes.values()) and self.is_safe()

    def run_for(self, ticks: int) -> None:
        """Run a fixed number of event-loop ticks (useful for fault scenarios)."""
        if ticks < 0:
            raise ValueError("ticks must be non-negative.")
        self._drive_consensus()
        for _ in range(ticks):
            self.step()

    def is_safe(self) -> bool:
        """Return false if correct nodes finalized different hashes at one height."""
        return not self.safety_violations and all(
            len(set(node_hashes.values())) <= 1
            for node_hashes in self.finalized_by_height.values()
        )

    def _drive_consensus(self) -> None:
        for node_id in sorted(self.nodes):
            node = self.nodes[node_id]
            height = node.consensus.height
            round_number = node.consensus.round
            if self._target_height is not None and height >= self._target_height:
                self._try_finalize(node)
                continue

            if self.auto_propose and node_id not in self.silent_nodes:
                proposal_key = (node_id, height, round_number)
                if (
                    proposal_key not in self._proposed_rounds
                    and node.consensus.is_current_proposer()
                ):
                    self._propose(node)

            for block in sorted(
                node.received_blocks.values(), key=lambda candidate: candidate.block_hash
            ):
                if block.header.height == height and block.header.round == round_number:
                    self._try_prevote(node, block)

            self._try_precommit(node)
            self._try_finalize(node)

    def _propose(self, node: Node) -> None:
        height, round_number = node.consensus.height, node.consensus.round
        proposal_key = (node.node_id, height, round_number)
        self._proposed_rounds.add(proposal_key)
        parent_hash = (
            node.finalized_blocks[-1].block_hash if node.finalized_blocks else "0" * 64
        )
        block = node.create_proposal_block(parent_hash)
        proposal_hash = block.header.header_hash
        self._blocks[proposal_hash] = block
        node.received_headers[proposal_hash] = block.header
        node.received_blocks[proposal_hash] = block
        node.logger.log_event(
            self.simulator.current_time,
            "proposal",
            height,
            {"round": round_number, "hash": block.block_hash},
        )

        payload = {
            "block_hash": block.block_hash,
            "proposal_hash": proposal_hash,
            "header": asdict(block.header),
        }
        self._header_history[proposal_key] = payload
        self._last_header_broadcast[proposal_key] = self.simulator.current_time
        self._broadcast(node.node_id, MessageType.HEADER, height, payload)
        self._try_prevote(node, block)

    def _try_prevote(self, node: Node, block: Block) -> None:
        if block.header.height != node.consensus.height:
            return
        if block.header.round != node.consensus.round:
            return
        vote = node.create_prevote_for_block(block)
        if vote is not None:
            node.logger.log_event(
                self.simulator.current_time,
                "prevote",
                vote.height,
                {"round": vote.round, "hash": vote.block_hash},
            )
            self._broadcast_vote(node, vote)

    def _try_precommit(self, node: Node) -> None:
        engine = node.consensus
        height, round_number = engine.height, engine.round
        candidates = [
            block
            for block in node.received_blocks.values()
            if block.header.height == height
            and block.header.round == round_number
            and engine.has_prevote_quorum(block.block_hash, height, round_number)
        ]
        if candidates:
            block = min(candidates, key=lambda item: item.block_hash)
            vote = engine.create_precommit(block.block_hash)
        elif engine.has_prevote_quorum(None, height, round_number):
            vote = engine.create_precommit(None)
        else:
            return

        if vote is not None:
            node.logger.log_event(
                self.simulator.current_time,
                "precommit",
                vote.height,
                {"round": vote.round, "hash": vote.block_hash},
            )
            self._broadcast_vote(node, vote)

    def _try_finalize(self, node: Node) -> None:
        height = node.consensus.height
        for block in sorted(
            node.received_blocks.values(), key=lambda candidate: candidate.block_hash
        ):
            if block.header.height != height:
                continue
            quorum_hash = node.consensus.check_precommit_quorum(
                block.header.height, block.header.round
            )
            if quorum_hash != block.block_hash:
                continue
            certificate = [
                vote
                for vote in node.consensus.lock_state.get_votes_for_phase(
                    height, block.header.round, VoteType.PRECOMMIT
                ).values()
                if vote.block_hash == block.block_hash
            ]
            finality_payload = self._finalized_payload(block, certificate)
            if node.finalize_block(block, certificate):
                self._record_finalization(node, block)
                self._remember_finalized(node.node_id, height, finality_payload)
                self._process_pending_finalized(node)
                break

    def _record_finalization(self, node: Node, block: Block) -> None:
        height = block.header.height
        finalized = self.finalized_by_height.setdefault(height, {})
        prior_hashes = set(finalized.values())
        if prior_hashes and block.block_hash not in prior_hashes:
            self.safety_violations.append(
                (height, min(prior_hashes), block.block_hash)
            )
        finalized[node.node_id] = block.block_hash
        node.logger.log_event(
            self.simulator.current_time,
            "finalize",
            height,
            {"hash": block.block_hash, "state_root": node.latest_state_root},
        )

    @staticmethod
    def _finalized_payload(block: Block, certificate: List[Vote]) -> Dict[str, object]:
        return {
            "block_hash": block.block_hash,
            "header": asdict(block.header),
            "transactions": [NetworkRunner._transaction_payload(tx) for tx in block.transactions],
            "precommits": [NetworkRunner._vote_payload(vote) for vote in certificate],
        }

    def _remember_finalized(
        self, source_id: str, height: int, payload: Dict[str, object]
    ) -> None:
        if height not in self._finalized_history:
            self._finalized_history[height] = (source_id, payload)
            self._last_finalized_broadcast[height] = self.simulator.current_time
        self._broadcast(source_id, MessageType.FINALIZED, height, payload)

    def _parse_finalized_payload(
        self, node: Node, payload: Dict[str, object]
    ) -> Tuple[Block, List[Vote]] | None:
        header = BlockHeader(**payload["header"])
        transactions = [
            self._transaction_from_payload(item) for item in payload["transactions"]
        ]
        block = Block(header, transactions)
        if payload.get("block_hash") != block.block_hash:
            return None
        votes = [self._vote_from_payload(item) for item in payload["precommits"]]
        if not node.consensus.verify_precommit_certificate(
            votes, block.block_hash, header.height, header.round
        ):
            return None
        return block, votes

    def _handle_finalized(self, node: Node, message: NetworkMessage) -> None:
        parsed = self._parse_finalized_payload(node, message.payload)
        if parsed is None:
            self._reject(node, message, "invalid_finality_certificate")
            return
        block, certificate = parsed
        if message.height != block.header.height:
            self._reject(node, message, "finality_height_mismatch")
            return
        if block.header.height < node.consensus.height:
            known = node.finalized_blocks[block.header.height - 1]
            if known.block_hash != block.block_hash:
                self.safety_violations.append(
                    (block.header.height, known.block_hash, block.block_hash)
                )
            return
        if block.header.height > node.consensus.height:
            self._pending_finalized.setdefault(node.node_id, {})[
                block.header.height
            ] = (message.sender_id, message.payload)
            return
        self._apply_finalized(node, message.sender_id, block, certificate, message.payload)

    def _apply_finalized(
        self,
        node: Node,
        source_id: str,
        block: Block,
        certificate: List[Vote],
        payload: Dict[str, object],
    ) -> bool:
        if block.header.round > node.consensus.round:
            node.consensus.round = block.header.round
        if not node.finalize_block(block, certificate):
            return False
        self._record_finalization(node, block)
        self._remember_finalized(source_id, block.header.height, payload)
        self._process_pending_finalized(node)
        return True

    def _process_pending_finalized(self, node: Node) -> None:
        pending = self._pending_finalized.get(node.node_id, {})
        while node.consensus.height in pending:
            height = node.consensus.height
            source_id, payload = pending.pop(height)
            parsed = self._parse_finalized_payload(node, payload)
            if parsed is None:
                continue
            block, certificate = parsed
            if not self._apply_finalized(node, source_id, block, certificate, payload):
                break

    def _advance_timed_out_rounds(self) -> None:
        now = self.simulator.current_time
        for node_id in sorted(self.nodes):
            node = self.nodes[node_id]
            height, round_number = node.consensus.height, node.consensus.round
            if self._target_height is not None and height >= self._target_height:
                continue
            key = (node_id, height, round_number)
            # Start a newly observed round's timer now. Using tick 0 here causes
            # later heights to time out immediately when the simulation is old.
            started = self._round_started.setdefault(key, now)
            # Give later rounds progressively more time for delayed proposals,
            # body requests, and vote broadcasts to complete.
            timeout_for_round = self.round_timeout_ticks * (round_number + 1)
            if now - started < timeout_for_round:
                continue

            old_proposer = node.consensus.get_proposer(height, round_number)
            node.consensus.advance_to_next_round()
            new_round_key = (node_id, height, node.consensus.round)
            self._round_started[new_round_key] = now
            node.logger.log_event(
                now,
                "round_timeout",
                height,
                {
                    "round": round_number,
                    "next_round": node.consensus.round,
                    "failed_proposer": old_proposer,
                },
            )

    def _retransmit(self) -> None:
        now = self.simulator.current_time
        # Retransmit only the newest proposal per node and height. This lets a
        # proposer that has moved rounds help lagging peers without repeatedly
        # flooding every historical proposal from that height.
        latest_headers: Dict[Tuple[str, int], Tuple[str, int, int]] = {}
        for proposal_key in self._header_history:
            node_id, height, round_number = proposal_key
            group_key = (node_id, height)
            previous = latest_headers.get(group_key)
            if previous is None or round_number > previous[2]:
                latest_headers[group_key] = proposal_key

        for proposal_key in sorted(latest_headers.values()):
            if now - self._last_header_broadcast[proposal_key] < self.retransmit_interval_ticks:
                continue
            node_id, height, _ = proposal_key
            if self._target_height is not None and height >= self._target_height:
                continue
            node = self.nodes[node_id]
            if node.consensus.height != height:
                continue
            self._broadcast(
                node_id,
                MessageType.HEADER,
                height,
                self._header_history[proposal_key],
            )
            self._last_header_broadcast[proposal_key] = now

        finalized_retransmit_interval = min(
            self.retransmit_interval_ticks, self.round_timeout_ticks
        )
        for height, (source_id, payload) in sorted(self._finalized_history.items()):
            if all(node.consensus.height > height for node in self.nodes.values()):
                continue
            if now - self._last_finalized_broadcast[height] < finalized_retransmit_interval:
                continue
            self._broadcast(source_id, MessageType.FINALIZED, height, payload)
            self._last_finalized_broadcast[height] = now

        for vote_key in sorted(self._vote_history):
            if now - self._last_vote_broadcast[vote_key] < self.retransmit_interval_ticks:
                continue
            node_id, height, round_number, _ = vote_key
            node = self.nodes[node_id]
            if node.consensus.height != height or round_number > node.consensus.round:
                continue
            self._broadcast(node_id, MessageType.VOTE, height, self._vote_history[vote_key])
            self._last_vote_broadcast[vote_key] = now

    def _broadcast_vote(self, node: Node, vote: Vote) -> None:
        phase = vote.phase.value
        vote_key = (node.node_id, vote.height, vote.round, phase)
        payload = self._vote_payload(vote)
        self._vote_history[vote_key] = payload
        self._last_vote_broadcast[vote_key] = self.simulator.current_time
        self._broadcast(node.node_id, MessageType.VOTE, vote.height, payload)

    def _broadcast(
        self,
        sender_id: str,
        msg_type: MessageType,
        height: int,
        payload: Dict[str, object],
        exclude: Optional[Iterable[str]] = None,
    ) -> None:
        excluded = set(exclude or ()) | {sender_id}
        for receiver_id in sorted(self.nodes):
            if receiver_id in excluded:
                continue
            self.simulator.send_message(
                NetworkMessage(msg_type, sender_id, receiver_id, height, payload)
            )

    def _send_to(
        self,
        sender_id: str,
        receiver_id: str,
        msg_type: MessageType,
        height: int,
        payload: Dict[str, object],
    ) -> None:
        self.simulator.send_message(
            NetworkMessage(msg_type, sender_id, receiver_id, height, payload)
        )

    def _handle_message(self, message: NetworkMessage) -> None:
        node = self.nodes[message.receiver_id]
        if message.sender_id not in self.nodes:
            self._reject(node, message, "unknown_sender")
            return
        try:
            if message.msg_type == MessageType.TX:
                self._handle_transaction(node, message)
            elif message.msg_type == MessageType.HEADER:
                self._handle_header(node, message)
            elif message.msg_type == MessageType.BODY_REQUEST:
                self._handle_body_request(node, message)
            elif message.msg_type == MessageType.BODY:
                self._handle_body(node, message)
            elif message.msg_type == MessageType.VOTE:
                self._handle_vote(node, message)
            elif message.msg_type == MessageType.FINALIZED:
                self._handle_finalized(node, message)
            else:
                self._reject(node, message, "unsupported_message_type")
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            self._reject(node, message, f"malformed_payload:{type(error).__name__}")

    def _handle_transaction(self, node: Node, message: NetworkMessage) -> None:
        tx = self._transaction_from_payload(message.payload["transaction"])
        accepted = node.add_pending_transaction(tx)
        node.logger.log_event(
            self.simulator.current_time,
            "tx_accepted" if accepted else "tx_rejected",
            message.height,
            {"hash": tx.tx_hash, "source": message.sender_id},
        )
        if not accepted:
            reason = (
                "invalid_signature_or_ownership"
                if not tx.is_valid(node.chain_id)
                else "duplicate_replay_or_nonce"
            )
            self._reject(node, message, reason)
        if accepted:
            self._broadcast(
                node.node_id,
                MessageType.TX,
                node.consensus.height,
                {"transaction": self._transaction_payload(tx)},
                exclude=(message.sender_id,),
            )

    def _handle_header(self, node: Node, message: NetworkMessage) -> None:
        header = BlockHeader(**message.payload["header"])
        block_hash = header.block_id
        proposal_hash = header.header_hash
        expected_sender = self._node_by_public_key.get(header.proposer)
        if (
            message.payload.get("block_hash") != block_hash
            or message.payload.get("proposal_hash") != proposal_hash
            or message.height != header.height
            or expected_sender != message.sender_id
            or not node.validate_proposal_header(header, require_current_round=False)
        ):
            self._reject(node, message, "invalid_or_unexpected_header")
            return

        node.received_headers[proposal_hash] = header
        self._body_requested.add((node.node_id, proposal_hash))
        node.logger.log_event(
            self.simulator.current_time,
            "header_accepted",
            header.height,
            {"round": header.round, "hash": block_hash, "sender": message.sender_id},
        )
        self._send_to(
            node.node_id,
            message.sender_id,
            MessageType.BODY_REQUEST,
            header.height,
            {"block_hash": block_hash, "proposal_hash": proposal_hash},
        )

    def _handle_body_request(self, node: Node, message: NetworkMessage) -> None:
        block_hash = str(message.payload["block_hash"])
        proposal_hash = str(message.payload["proposal_hash"])
        block = self._blocks.get(proposal_hash)
        if (
            block is None
            or block.block_hash != block_hash
            or block.header.proposer != node.public_key_hex
        ):
            self._reject(node, message, "unknown_body_request")
            return
        self._send_to(
            node.node_id,
            message.sender_id,
            MessageType.BODY,
            block.header.height,
            {
                "block_hash": block_hash,
                "proposal_hash": proposal_hash,
                "transactions": [self._transaction_payload(tx) for tx in block.transactions],
            },
        )

    def _handle_body(self, node: Node, message: NetworkMessage) -> None:
        block_hash = str(message.payload["block_hash"])
        proposal_hash = str(message.payload["proposal_hash"])
        header = node.received_headers.get(proposal_hash)
        if header is None or (node.node_id, proposal_hash) not in self._body_requested:
            self._reject(node, message, "body_without_accepted_header")
            return
        expected_sender = self._node_by_public_key.get(header.proposer)
        if expected_sender != message.sender_id or message.height != header.height:
            self._reject(node, message, "body_sender_or_height_mismatch")
            return

        transactions = [
            self._transaction_from_payload(item)
            for item in message.payload["transactions"]
        ]
        block = Block(header, transactions)
        if (
            block.block_hash != block_hash
            or block.header.header_hash != proposal_hash
            or not node.validate_proposal_block(
            block, require_current_round=False
            )
        ):
            self._reject(node, message, "invalid_block_body_or_state_root")
            return

        self._blocks[proposal_hash] = block
        node.received_blocks[proposal_hash] = block
        node.logger.log_event(
            self.simulator.current_time,
            "body_accepted",
            block.header.height,
            {"round": block.header.round, "hash": block_hash},
        )
        self._try_prevote(node, block)

    def _handle_vote(self, node: Node, message: NetworkMessage) -> None:
        vote = self._vote_from_payload(message.payload)
        expected_sender = self._node_by_public_key.get(vote.validator)
        reason = None
        if expected_sender != message.sender_id:
            reason = "sender_identity_mismatch"
        elif message.height != vote.height or vote.height != node.consensus.height:
            reason = "height_mismatch"
        elif vote.validator not in node.validator_keys:
            reason = "unknown_validator"
        elif not vote.is_valid(node.chain_id):
            reason = "invalid_signature_or_domain"
        elif vote.round < 0 or vote.round > node.consensus.round:
            reason = "invalid_round"

        accepted = reason is None and node.receive_vote(vote)
        if not accepted and reason is None:
            reason = "duplicate_conflicting_or_invalid_vote"
        node.logger.log_event(
            self.simulator.current_time,
            "vote_accepted" if accepted else "vote_rejected",
            message.height,
            {
                "sender": message.sender_id,
                "phase": vote.phase.value,
                "round": vote.round,
                "hash": vote.block_hash,
                "reason": reason,
            },
        )
        if not accepted:
            return
        if vote.phase == VoteType.PREVOTE:
            node.logger.log_event(
                self.simulator.current_time,
                "prevote_received",
                vote.height,
                {"round": vote.round, "hash": vote.block_hash},
            )

    def _reject(self, node: Node, message: NetworkMessage, reason: str) -> None:
        node.logger.log_event(
            self.simulator.current_time,
            "message_rejected",
            message.height,
            {"type": message.msg_type.value, "sender": message.sender_id, "reason": reason},
        )

    @staticmethod
    def _transaction_payload(tx: Transaction) -> Dict[str, object]:
        return {
            "sender": tx.sender,
            "key": tx.key,
            "value": tx.value,
            "nonce": tx.nonce,
            "signature": tx.signature,
        }

    @staticmethod
    def _transaction_from_payload(payload: object) -> Transaction:
        if not isinstance(payload, dict):
            raise TypeError("transaction payload must be an object")
        return Transaction(**payload)

    @staticmethod
    def _vote_payload(vote: Vote) -> Dict[str, object]:
        return {
            "validator": vote.validator,
            "height": vote.height,
            "round": vote.round,
            "phase": vote.phase.value,
            "block_hash": vote.block_hash,
            "signature": vote.signature,
        }

    @staticmethod
    def _vote_from_payload(payload: object) -> Vote:
        if not isinstance(payload, dict):
            raise TypeError("vote payload must be an object")
        data = dict(payload)
        data["phase"] = VoteType(data["phase"])
        return Vote(**data)
