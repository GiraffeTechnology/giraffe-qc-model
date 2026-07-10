"""Headless pairing agent (P0 addendum §1) — runs on the Jetson.

No screen, so **no QR and no on-device confirm button**. Two paths:

* **USB (Path A):** the physical cable is the authorization — whoever plugs in is
  standing at the machine. Pairing over the USB interface is always allowed.
* **Wi-Fi (Path B):** pairing is only accepted inside a **pairing window** opened
  by a physical trigger (button / boot-into-pairing-mode). Within the window the
  admin verifies the chassis-sticker fingerprint on the Pad; outside the window
  every request is rejected outright.

Pairing establishes a per-pair key and is **1:1**: a new pairing (either path)
replaces the previous binding immediately, with **no grace period** — the old
Pad's signed requests stop verifying the instant a re-pair completes.

Pairing never requires Server reachability (floor first, sync later).
"""
from __future__ import annotations

import secrets
import time
from typing import Callable, Optional

from jetson_runner.app.identity import JetsonIdentity
from src.qc_model.jetson.identity import fingerprints_match


class PairingRejected(Exception):
    pass


class PairingAgent:
    def __init__(self, identity: JetsonIdentity, clock: Callable[[], float] = time.monotonic):
        self.identity = identity
        self._clock = clock
        self.paired_pad_device_id: Optional[str] = None
        self.pair_key: Optional[str] = None
        self.pairing_path: Optional[str] = None
        self._window_until: float = 0.0

    # ── Wi-Fi pairing window (opened by a physical trigger) ──────────────────
    def open_pairing_window(self, seconds: float = 120.0) -> None:
        self._window_until = self._clock() + seconds

    def pairing_window_open(self) -> bool:
        return self._clock() < self._window_until

    # ── Path A: USB (physical proof) ─────────────────────────────────────────
    def pair_usb(self, pad_device_id: str, pad_pubkey: str) -> dict:
        return self._establish(pad_device_id, pad_pubkey, path="usb")

    # ── Path B: Wi-Fi (window + fingerprint verification) ────────────────────
    def pair_wifi(self, pad_device_id: str, pad_pubkey: str, confirmed_fingerprint: str) -> dict:
        if not self.pairing_window_open():
            raise PairingRejected("pairing_window_closed")
        if not fingerprints_match(confirmed_fingerprint, self.identity.fingerprint):
            raise PairingRejected("fingerprint_mismatch")
        result = self._establish(pad_device_id, pad_pubkey, path="wifi")
        self._window_until = 0.0  # close the window after a successful pairing
        return result

    def _establish(self, pad_device_id: str, pad_pubkey: str, *, path: str) -> dict:
        # Re-pair replaces the previous binding immediately (fail-closed).
        self.pair_key = secrets.token_hex(32)
        self.paired_pad_device_id = pad_device_id
        self.pairing_path = path
        return {
            "jetson_device_id": self.identity.jetson_device_id,
            "jetson_pubkey": self.identity.pubkey,
            "pair_key": self.pair_key,
            "pairing_path": path,
        }

    def unpair(self) -> None:
        self.paired_pad_device_id = None
        self.pair_key = None
        self.pairing_path = None

    # ── Auth check for inference requests ────────────────────────────────────
    def is_paired_to(self, pad_device_id: str) -> bool:
        return self.pair_key is not None and pad_device_id == self.paired_pad_device_id
