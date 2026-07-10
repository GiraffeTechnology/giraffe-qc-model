"""Per-pair request signing (paired-identity auth, §3 / §7).

Pairing establishes a **per-pair** shared key (unique to one Pad↔Jetson pair —
never a global static secret). Every Pad→Jetson inference request is signed with
that key; the Jetson verifies with the same key and rejects anything that does
not verify against its *one* current paired identity.

This is the minimal-dependency stand-in the mock uses (HMAC-SHA256 over the
canonical request). A production build would use mutual TLS / asymmetric keys
exchanged at pairing — the property that matters, and that this preserves, is
"paired identity, not a shared secret across all devices".
"""
from __future__ import annotations

import hashlib
import hmac
import json


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign(pair_key: str, payload: dict) -> str:
    return hmac.new(pair_key.encode("utf-8"), canonical(payload), hashlib.sha256).hexdigest()


def verify(pair_key: str, payload: dict, signature: str) -> bool:
    if not pair_key or not signature:
        return False
    return hmac.compare_digest(sign(pair_key, payload), signature)
