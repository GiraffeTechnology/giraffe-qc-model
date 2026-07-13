"""Jetson provisioning identity (created off-floor, headless).

Each Jetson is flashed with a unique ``jetson_device_id`` + keypair and a chassis
label carrying the pubkey fingerprint (for Path B / Wi-Fi verification). Here the
"keypair" is a random secret whose public half is a derived token; the fingerprint
is computed the same way the Server does (``src.qc_model.jetson.identity``) so the
sticker and the Pad-side display always agree.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from src.qc_model.jetson.identity import derive_fingerprint


@dataclass
class JetsonIdentity:
    jetson_device_id: str
    private_key: str
    pubkey: str
    fingerprint: str

    @property
    def chassis_label(self) -> str:
        """The human-readable sticker printed at provisioning time."""
        return f"{self.jetson_device_id} / {self.fingerprint}"


def generate_identity(device_id: str | None = None) -> JetsonIdentity:
    """Provision a fresh identity (bench/off-floor step)."""
    device_id = device_id or f"jetson-{secrets.token_hex(4)}"
    private_key = secrets.token_hex(32)
    # Stand-in "public key": deterministic from the private key.
    pubkey = derive_fingerprint(private_key, groups=8, group_len=8).replace("-", "")
    return JetsonIdentity(
        jetson_device_id=device_id,
        private_key=private_key,
        pubkey=pubkey,
        fingerprint=derive_fingerprint(pubkey),
    )
