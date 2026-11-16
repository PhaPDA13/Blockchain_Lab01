"""Run one deterministic one-block validator simulation from a JSON config."""
import argparse
import json
from pathlib import Path

from src.crypto.identity import KeyPair
from src.execution.transaction import Transaction
from src.network.runner import NetworkRunner
from src.node import Node


def build_nodes(config):
    num_nodes = int(config.get("num_nodes", 10))
    if num_nodes < 8 or (num_nodes - 1) % 3 != 0:
        raise ValueError("Validator count must satisfy n = 3f + 1 and n >= 8.")

    seed = int(config.get("random_seed", 42))
    key_pairs = [
        KeyPair.from_seed(bytes([(seed + index) % 256] * 32))
        for index in range(num_nodes)
    ]
    validator_keys = [key_pair.public_key_hex for key_pair in key_pairs]
    nodes = [
        Node(f"node_{index}", key_pairs[index], str(config["chain_id"]), validator_keys)
        for index in range(num_nodes)
    ]
    return nodes, key_pairs


def main():
    project_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=project_dir / "config" / "default_config.json",
        help="JSON network configuration",
    )
    parser.add_argument("--max-ticks", type=int, default=10_000)
    parser.add_argument(
        "--write-logs",
        type=Path,
        help="Optional new directory for canonical node and transport logs",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    nodes, key_pairs = build_nodes(config)
    runner = NetworkRunner.from_config(nodes, config)
    chain_id = str(config["chain_id"])

    tx = Transaction(
        sender=key_pairs[0].public_key_hex,
        key=f"{key_pairs[0].public_key_hex}/message",
        value="hello-lab01",
        nonce=0,
    )
    tx.sign(key_pairs[0], chain_id)
    proposer = next(
        node
        for node in nodes
        if node.public_key_hex == node.consensus.get_proposer(height=1, round=0)
    )
    if not runner.submit_transaction(tx, proposer.node_id):
        raise RuntimeError("The demo transaction was rejected by its ingress node.")
    if not runner.run_until_finalized(1, max_ticks=args.max_ticks):
        raise RuntimeError(
            f"Validators did not finalize height 1 within {args.max_ticks} ticks."
        )

    block_hashes = {node.finalized_blocks[0].block_hash for node in nodes}
    state_roots = {node.latest_state_root for node in nodes}
    if len(block_hashes) != 1 or len(state_roots) != 1:
        raise RuntimeError("Validators did not converge on one block and state root.")

    print(f"finalized_height=1")
    print(f"block_hash={next(iter(block_hashes))}")
    print(f"state_root={next(iter(state_roots))}")
    print(f"simulated_ticks={runner.simulator.current_time}")
    print(f"network_events={len(runner.simulator.logger.entries)}")

    if args.write_logs is not None:
        log_dir = args.write_logs.resolve()
        if log_dir.exists():
            raise FileExistsError(f"Log directory already exists: {log_dir}")
        log_dir.mkdir(parents=True)
        for node in nodes:
            (log_dir / f"{node.node_id}.json").write_bytes(
                node.logger.export_canonical_bytes()
            )
        (log_dir / "network.json").write_bytes(
            runner.simulator.logger.export_canonical_bytes()
        )
        print(f"logs={log_dir}")


if __name__ == "__main__":
    main()
