"""
Deterministic canonical byte encoding.
Ensures identical logical content always produces byte-identical results across nodes.
"""
import json
from typing import Any


def canonical_encode(data: Any) -> bytes:
    """
    Encode python data structures into canonical deterministic UTF-8 bytes.
    Keys are sorted, separators are compact (no extra spaces).
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
