"""Unit checks for delivery callbacks, outbound limits, and peer blocking."""
from src.network.message import MessageType, NetworkMessage
from src.network.simulator import NetworkSimulator


def make_message(sender, receiver, height=1):
    return NetworkMessage(MessageType.TX, sender, receiver, height, {"value": "x"})


def test_outbound_rate_limit_drops_excess_messages_in_window():
    simulator = NetworkSimulator(
        ["node_a", "node_b"],
        seed=1,
        min_delay=1,
        max_delay=1,
        stabilization_time=0,
        delta_bound=1,
        max_outbound_rate=1,
        rate_window_ticks=10,
    )

    simulator.send_message(make_message("node_a", "node_b"))
    simulator.send_message(make_message("node_a", "node_b"))

    assert simulator.has_pending_messages() is True
    assert all(entry["node_id"] == "node_a" for entry in simulator.logger.entries)
    assert [entry["type"] for entry in simulator.logger.entries] == [
        "send",
        "delay",
        "send",
        "drop",
    ]
    assert simulator.logger.entries[-1]["details"]["reason"] == "outbound_rate_limit"


def test_peer_block_and_unblock_are_logged_and_enforced():
    simulator = NetworkSimulator(["node_a", "node_b"], seed=2)
    simulator.block_peer("node_a", "node_b")
    simulator.send_message(make_message("node_a", "node_b"))
    assert simulator.has_pending_messages() is False
    assert simulator.logger.entries[0]["node_id"] == "node_a"
    assert simulator.logger.entries[2]["node_id"] == "node_b"

    simulator.unblock_peer("node_a", "node_b")
    simulator.send_message(make_message("node_a", "node_b"))
    assert simulator.has_pending_messages() is True
    assert [entry["type"] for entry in simulator.logger.entries] == [
        "block",
        "send",
        "block",
        "unblock",
        "send",
        "delay",
    ]


def test_registered_handler_receives_delivered_message():
    simulator = NetworkSimulator(
        ["node_a", "node_b"],
        seed=3,
        min_delay=1,
        max_delay=1,
        stabilization_time=0,
        delta_bound=1,
    )
    received = []
    simulator.register_handler("node_b", received.append)
    message = make_message("node_a", "node_b")

    simulator.send_message(message)
    assert simulator.step() == 1
    assert received == [message]
    assert simulator.inboxes["node_b"] == [message]
