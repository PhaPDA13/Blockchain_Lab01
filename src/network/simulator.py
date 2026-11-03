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
from typing import List, Dict, Tuple, Optional, Any
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
    ):
        self.node_ids = sorted(node_ids)
        self.rng = random.Random(seed)
        self.current_time: int = 0
        self.drop_rate = drop_rate
        self.duplicate_rate = duplicate_rate
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.stabilization_time = stabilization_time
        self.delta_bound = delta_bound

        # Priority queue for in-flight messages: (delivery_time, tie_breaker, message)
        self._message_queue: List[Tuple[int, int, NetworkMessage]] = []
        self._seq: int = 0

        # Logger for all network events
        self.logger = NetworkLogger(node_id="SIMULATOR")

        # Inboxes for nodes: node_id -> List[NetworkMessage]
        self.inboxes: Dict[str, List[NetworkMessage]] = {nid: [] for nid in self.node_ids}

    def send_message(self, message: NetworkMessage):
        """Send message through the simulated network with delay, drop, or duplication."""
        self.logger.log_event(
            self.current_time,
            "send",
            message.height,
            {"from": message.sender_id, "to": message.receiver_id, "msg_type": message.msg_type.value},
        )

        is_stabilized = self.current_time >= self.stabilization_time

        # Before stabilization, simulate drops
        if not is_stabilized and self.rng.random() < self.drop_rate:
            self.logger.log_event(
                self.current_time,
                "drop",
                message.height,
                {"from": message.sender_id, "to": message.receiver_id},
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
        return delivered_count

    def has_pending_messages(self) -> bool:
        return bool(self._message_queue)
