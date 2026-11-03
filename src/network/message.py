"""
Network message types and framing.
Headers are broadcast before bodies; bodies sent only after receiver accepts header.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class MessageType(str, Enum):
    TX = "TX"
    HEADER = "HEADER"
    BODY_REQUEST = "BODY_REQUEST"
    BODY = "BODY"
    VOTE = "VOTE"


@dataclass
class NetworkMessage:
    msg_type: MessageType
    sender_id: str
    receiver_id: str
    height: int
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.msg_type.value,
            "sender": self.sender_id,
            "receiver": self.receiver_id,
            "height": self.height,
            "payload": self.payload,
        }
