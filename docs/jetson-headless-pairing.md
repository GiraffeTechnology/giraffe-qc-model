# Headless Jetson Pairing (P0)

**Production constraint (P0): the Jetson has no display, keyboard, or mouse.**
So pairing cannot use a QR shown on the Jetson or a "confirm on device" button.
This document describes the two headless pairing paths and the fail-closed
security model. (Server-side record: `src/qc_model/jetson/service.py`; device
side: `jetson_runner/app/pairing_agent.py`.)

## Provisioning (one-time, off-floor)

Each Jetson is flashed on a bench (monitor/SSH is fine there) with:

- a unique `jetson_device_id` + keypair;
- the pairing agent installed and enabled at boot;
- a **chassis sticker**: device ID + a short numeric **pubkey fingerprint**
  (`NNNN-NNNN-NNNN-NNNN`, from `derive_fingerprint`) for Path B verification.

Provisioning is internal setup, never an operator flow. No HDMI step exists in
any floor runbook.

## Path A — USB (primary, recommended for first setup)

The physical USB cable **is** the authorization: whoever plugs it in is standing
at the machine.

1. Connect Pad ↔ Jetson via USB (Jetson presents as a USB network device).
2. Pad discovers the pairing agent on the fixed well-known address on that USB
   interface only.
3. Pad → `{workstation_id, pad_device_id, pad_pubkey}`; Jetson →
   `{jetson_device_id, jetson_pubkey, capabilities}` and a **per-pair key**.
4. Both persist the peer identity. Pad registers the binding with the Server on
   its next sync — **pairing itself never requires Server reachability** (floor
   first, sync later).

## Path B — Wi-Fi / LAN (re-pair, or when USB is impractical)

No screen ⇒ no QR, no on-device button. Instead:

1. A **physical trigger** (button / boot-into-pairing-mode) opens a **pairing
   window** for N minutes. Outside the window, all pairing requests are rejected
   outright.
2. During the window the Jetson announces itself (mDNS) as `jetson_runner`.
3. The Pad shows the device ID + the numeric **fingerprint**; the admin verifies
   it against the **chassis sticker** and confirms on the Pad.
4. On match → same key exchange as Path A. The window closes after success.

## Post-pairing authentication (§3, §7) — fail-closed

- Every Pad→Jetson inference request is signed with the **per-pair key** (unique
  to that one Pad↔Jetson pair — never a shared secret across devices). The mock
  uses HMAC-SHA256; production would use mTLS / asymmetric keys. The property
  that matters: the *paired* identity, not a global secret.
- The Jetson accepts requests only from its **one** current paired Pad (1:1). An
  unpaired/unknown caller or a bad/tampered signature is rejected — no inference
  runs.
- **Re-pair replaces the previous binding immediately, with no grace period.**
  The instant a new Pad pairs, the old Pad's signed requests stop verifying.

## Status visibility (§4 addendum)

All Jetson state surfaces on the **Pad** (the only screen): paired Jetson ID,
connection/readiness state, agent version, last-seen, and — during Path B — the
"pairing window open on device X" state. On the admin side the workstation page
(S3) shows the Jetson binding alongside the Pad.

## Server binding record (1:1)

When the Pad syncs a pairing (`POST /api/qc/jetson/bindings`), the Server:

- auto-provisions the runner if it hasn't seen it (sync tolerance);
- frees the target workstation from any *other* Jetson it was bound to;
- replaces this Jetson's previous binding (re-pair) and writes an audit event
  (`paired` / `repaired` / `unpaired`);

so the Server record always reflects exactly one current Pad↔Jetson pair.

## Acceptance (addendum §5) — how this is verified

See `jetson_runner/tests/test_pairing.py` and
`tests/integration/test_jetson_pad_inference.py`:

- USB pairing with zero Jetson-side interaction beyond the cable ✓
- Wi-Fi pairing needs an open window + fingerprint match; outside the window is
  rejected ✓
- pairing works with the Server unreachable; binding syncs later ✓
- after re-pair, the old Pad is rejected with no grace ✓
- all status is available on the Pad; no flow assumes a Jetson display ✓
