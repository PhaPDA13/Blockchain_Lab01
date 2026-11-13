"""
Discrete-event network simulator modeling partially synchronous unreliable communication.
Supports:
- Random delay, duplicate, reorder, and drop before stabilization time
- Outbound rate limits and peer blocking
- Configurable number of nodes (>= 8)
- Deterministic execution driven by random seed
"""
import random
import heapq
from collections import deque
from typing import Callable, List, Dict, Tuple, Optional, Any, Set, Deque
from .message import NetworkMessage
from .logger import NetworkLogger


class NetworkSimulator:
    def __init__(
        self,
        node_ids: List[str],
        seed: int = 42,
        drop_rate: float = 0.0,
        duplicate_rate: float = 0.0,
        min_delay: int = 1,
        max_delay: int = 5,
        stabilization_time: int = 1000,
        delta_bound: int = 2,
        max_outbound_rate: Optional[int] = None,
        rate_window_ticks: int = 1000,
    ):
        if not node_ids or len(set(node_ids)) != len(node_ids):
            raise ValueError("node_ids must be non-empty and unique.")
        if not 0.0 <= drop_rate <= 1.0 or not 0.0 <= duplicate_rate <= 1.0:
            raise ValueError("drop_rate and duplicate_rate must be between 0 and 1.")
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("Delay bounds must satisfy 0 <= min_delay <= max_delay.")
        if stabilization_time < 0 or delta_bound < 0:
            raise ValueError("stabilization_time and delta_bound must be non-negative.")
        if max_outbound_rate is not None and max_outbound_rate < 1:
            raise ValueError("max_outbound_rate must be positive when configured.")
        if rate_window_ticks < 1:
            raise ValueError("rate_window_ticks must be positive.")

        self.node_ids = sorted(node_ids)
        self.rng = random.Random(seed)
        self.current_time: int = 0
        self.drop_rate = drop_rate
        self.duplicate_rate = duplicate_rate
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.stabilization_time = stabilization_time
        self.delta_bound = delta_bound
        self.max_outbound_rate = max_outbound_rate
        self.rate_window_ticks = rate_window_ticks
        self._blocked_pairs: Set[frozenset[str]] = set()
        self._outbound_times: Dict[str, Deque[int]] = {
            node_id: deque() for node_id in self.node_ids
        }
        self._handlers: Dict[str, Callable[[NetworkMessage], None]] = {}

        # Priority queue for in-flight messages: (delivery_time, tie_breaker, message)
        self._message_queue: List[Tuple[int, int, NetworkMessage]] = []
        self._seq: int = 0

        # Logger for all network events
        self.logger = NetworkLogger(node_id="SIMULATOR")

        # Inboxes for nodes: node_id -> List[NetworkMessage]
        self.inboxes: Dict[str, List[NetworkMessage]] = {nid: [] for nid in self.node_ids}

    def send_message(self, message: NetworkMessage):
        """Send message through the simulated network with delay, drop, or duplication."""
        if message.sender_id not in self.inboxes or message.receiver_id not in self.inboxes:
            raise ValueError("Message endpoints must be registered network nodes.")

        self.logger.log_event(
            self.current_time,
            "send",
            message.height,
            {"from": message.sender_id, "to": message.receiver_id, "msg_type": message.msg_type.value},
            node_id=message.sender_id,
        )

        peer_pair = frozenset((message.sender_id, message.receiver_id))
        if peer_pair in self._blocked_pairs:
            self.logger.log_event(
                self.current_time,
                "block",
                message.height,
                {"node_id": message.receiver_id, "peer_id": message.sender_id},
                node_id=message.receiver_id,
            )
            return

        sender_times = self._outbound_times[message.sender_id]
        cutoff = self.current_time - self.rate_window_ticks
        while sender_times and sender_times[0] <= cutoff:
            sender_times.popleft()
        if self.max_outbound_rate is not None and len(sender_times) >= self.max_outbound_rate:
            self.logger.log_event(
                self.current_time,
                "drop",
                message.height,
                {
                    "from": message.sender_id,
                    "to": message.receiver_id,
                    "reason": "outbound_rate_limit",
                },
                node_id=message.sender_id,
            )
            return
        sender_times.append(self.current_time)

        is_stabilized = self.current_time >= self.stabilization_time

        # Before stabilization, simulate drops
        if not is_stabilized and self.rng.random() < self.drop_rate:
            self.logger.log_event(
                self.current_time,
                "drop",
                message.height,
                {"from": message.sender_id, "to": message.receiver_id},
                node_id=message.sender_id,
            )
            return

        # Calculate delay
        if is_stabilized:
            delay = self.rng.randint(1, max(1, self.delta_bound))
        else:
            delay = self.rng.randint(self.min_delay, self.max_delay)

        delivery_time = self.current_time + delay
        self._seq += 1
        heapq.heappush(self._message_queue, (delivery_time, self._seq, message))
        self.logger.log_event(
            self.current_time,
            "delay",
            message.height,
            {
                "from": message.sender_id,
                "to": message.receiver_id,
                "ticks": delay,
                "delivery_time": delivery_time,
            },
            node_id=message.sender_id,
        )

        # Check duplication
        if not is_stabilized and self.rng.random() < self.duplicate_rate:
            dup_delay = delivery_time + self.rng.randint(1, 3)
            self._seq += 1
            heapq.heappush(self._message_queue, (dup_delay, self._seq, message))
            self.logger.log_event(
                self.current_time,
                "duplicate",
                message.height,
                {"from": message.sender_id, "to": message.receiver_id},
                node_id=message.sender_id,
            )

    def step(self) -> int:
        """Advance simulation clock by 1 tick and deliver all ready messages."""
        self.current_time += 1
        delivered_count = 0
        while self._message_queue and self._message_queue[0][0] <= self.current_time:
            _, _, msg = heapq.heappop(self._message_queue)
            if msg.receiver_id in self.inboxes:
                self.inboxes[msg.receiver_id].append(msg)
                delivered_count += 1
                handler = self._handlers.get(msg.receiver_id)
                if handler is not None:
                    handler(msg)
        return delivered_count

    def register_handler(
        self, node_id: str, handler: Callable[[NetworkMessage], None]
    ) -> None:
        """Register the event-loop callback for a node's delivered messages."""
        if node_id not in self.inboxes:
            raise ValueError(f"Unknown node: {node_id}")
        self._handlers[node_id] = handler

    def block_peer(self, node_id: str, peer_id: str) -> None:
        """Block traffic in both directions between two peers."""
        if node_id not in self.inboxes or peer_id not in self.inboxes:
            raise ValueError("Both peers must be registered network nodes.")
        pair = frozenset((node_id, peer_id))
        if pair not in self._blocked_pairs:
            self._blocked_pairs.add(pair)
            self.logger.log_event(
                self.current_time,
                "block",
                0,
                {"node_id": node_id, "peer_id": peer_id, "action": "block_peer"},
                node_id=node_id,
            )

    def unblock_peer(self, node_id: str, peer_id: str) -> None:
        """Restore traffic in both directions between two peers."""
        pair = frozenset((node_id, peer_id))
        if pair in self._blocked_pairs:
            self._blocked_pairs.remove(pair)
            self.logger.log_event(
                self.current_time,
                "unblock",
                0,
                {"node_id": node_id, "peer_id": peer_id},
                node_id=node_id,
            )

    def has_pending_messages(self) -> bool:
        return bool(self._message_queue)
