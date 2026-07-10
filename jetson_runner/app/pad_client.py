"""Mock Pad-side orchestration for the Pad↔Jetson contract (test/dev helper).

The real Pad is the Android app; this mirrors just enough of its behaviour to
exercise the pairing + signed-inference contract end-to-end without hardware:
pair (USB or Wi-Fi), then build and sign inference requests with the per-pair
key. It also shows how the Pad reports the binding to the Server on sync.
"""
from __future__ import annotations

import secrets
from typing import Optional

from jetson_runner.app import signing


class MockPad:
    def __init__(self, pad_device_id: Optional[str] = None):
        self.pad_device_id = pad_device_id or f"pad-{secrets.token_hex(3)}"
        self.pubkey = f"padpub-{secrets.token_hex(8)}"
        self.pair_key: Optional[str] = None
        self.jetson_device_id: Optional[str] = None
        self.pairing_path: Optional[str] = None

    def _store(self, handshake: dict) -> None:
        self.pair_key = handshake["pair_key"]
        self.jetson_device_id = handshake["jetson_device_id"]
        self.pairing_path = handshake["pairing_path"]

    def pair_over_usb(self, agent) -> dict:
        hs = agent.pair_usb(self.pad_device_id, self.pubkey)
        self._store(hs)
        return hs

    def pair_over_wifi(self, agent, confirmed_fingerprint: str) -> dict:
        hs = agent.pair_wifi(self.pad_device_id, self.pubkey, confirmed_fingerprint)
        self._store(hs)
        return hs

    def signed_inference(self, request: dict) -> dict:
        """Return the wire envelope the Pad POSTs to the Jetson /infer endpoint."""
        return {
            "pad_device_id": self.pad_device_id,
            "signature": signing.sign(self.pair_key, request),
            "request": request,
        }

    def call(self, service, request: dict) -> dict:
        env = self.signed_inference(request)
        return service.handle_inference(
            pad_device_id=env["pad_device_id"], signature=env["signature"], payload=env["request"]
        )

    def binding_sync_payload(self, workstation_id: str, fingerprint: str, tenant_id: str = "default") -> dict:
        """What the Pad POSTs to the Server (/api/qc/jetson/bindings) on sync."""
        return {
            "tenant_id": tenant_id,
            "jetson_device_id": self.jetson_device_id,
            "pubkey_fingerprint": fingerprint,
            "workstation_id": workstation_id,
            "pad_device_id": self.pad_device_id,
            "pairing_path": self.pairing_path,
        }
