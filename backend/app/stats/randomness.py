"""Stable seeds independent of process hash randomization."""

import hashlib
import json


def derive_seed(*parts: str) -> int:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
