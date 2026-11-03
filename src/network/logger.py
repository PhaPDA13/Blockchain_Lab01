"""
Deterministic event logging for consensus and network events.
Uses logical/simulated timestamps to guarantee byte-identical logs across runs with same seed.
"""
from typing import List, Dict, Any
from ..crypto.encoding import canonical_encode


class NetworkLogger:
    """Logs all network and consensus events deterministically."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.entries: List[Dict[str, Any]] = []

    def log_event(
        self,
        logical_time: int,
        event_type: str,  # send, drop, delay, block, unblock, vote, finalize
        height: int,
        details: Dict[str, Any] = None,
    ):
        """Record an event with deterministic logical time, node_id, type, and height."""
        entry = {
            "time": logical_time,
            "node_id": self.node_id,
            "type": event_type,
            "height": height,
            "details": details or {},
        }
        self.entries.append(entry)

    def export_text_log(self) -> str:
        """Export readable, deterministic log representation."""
        lines = []
        for e in self.entries:
            lines.append(
                f"[{e['time']:06d}] node={e['node_id']} type={e['type']} height={e['height']} details={e['details']}"
            )
        return "\n".join(lines) + "\n"

    def export_canonical_bytes(self) -> bytes:
        """Export byte-identical canonical byte representation."""
        return canonical_encode(self.entries)
