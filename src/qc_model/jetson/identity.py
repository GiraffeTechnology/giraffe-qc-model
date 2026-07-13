"""Provisioning identity + fingerprint helpers for the Jetson runner.

Because the production Jetson is headless (no screen/QR), Path B (Wi-Fi) pairing
relies on a **short numeric fingerprint** derived from the Jetson's public key
and printed on a chassis sticker at provisioning time. The admin verifies the
fingerprint shown on the Pad against the sticker before confirming the pairing.

``derive_fingerprint`` produces a stable, human-checkable code from any public
key material. It is deterministic so the sticker (generated at provisioning) and
the Pad-side display (derived from the received pubkey) always agree.
"""
from __future__ import annotations

import hashlib


def derive_fingerprint(pubkey: str, groups: int = 4, group_len: int = 4) -> str:
    """Derive a short, human-readable numeric fingerprint from a public key.

    Format: ``groups`` blocks of ``group_len`` digits, dash-separated
    (default ``NNNN-NNNN-NNNN-NNNN``). Deterministic for a given key.
    """
    digest = hashlib.sha256(pubkey.encode("utf-8")).digest()
    # Turn the digest into a decimal string and slice fixed-width groups.
    decimal = str(int.from_bytes(digest, "big"))
    needed = groups * group_len
    decimal = (decimal * ((needed // len(decimal)) + 1))[:needed]
    return "-".join(decimal[i : i + group_len] for i in range(0, needed, group_len))


def fingerprints_match(a: str, b: str) -> bool:
    """Constant-ish comparison of two fingerprints, tolerant of spacing/case."""
    import hmac

    def _norm(s: str) -> str:
        return "".join(ch for ch in s if ch.isdigit())

    return hmac.compare_digest(_norm(a), _norm(b))
