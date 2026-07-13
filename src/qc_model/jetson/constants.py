"""Enums / allowed values for the Jetson Xavier NX inference runner."""
from __future__ import annotations

# ── Device type (§2) ─────────────────────────────────────────────────────────
DEVICE_TYPE_JETSON_RUNNER = "jetson_runner"

# ── Pairing status ───────────────────────────────────────────────────────────
PAIRING_UNPAIRED = "unpaired"
PAIRING_PAIRED = "paired"
PAIRING_STATUSES = frozenset({PAIRING_UNPAIRED, PAIRING_PAIRED})

# ── Pairing path (P0 addendum §1) ────────────────────────────────────────────
PAIRING_PATH_USB = "usb"
PAIRING_PATH_WIFI = "wifi"
PAIRING_PATHS = frozenset({PAIRING_PATH_USB, PAIRING_PATH_WIFI})

# ── Runtime readiness states (§5) ────────────────────────────────────────────
# NOTE: fail-closed — when the Jetson is unreachable the operator cannot submit
# an inspection; the Pad must never fabricate a verdict or fall back to another
# model.
READY = "jetson_ready"                 # Jetson connected & ready
CONNECTING = "jetson_connecting"       # Jetson connecting...
UNREACHABLE = "jetson_unreachable"     # offline mode — inspection blocked
NO_STANDARD = "no_standard_installed"  # No standard installed
NO_SKU = "no_sku_selected"             # No SKU selected

READINESS_STATES = frozenset({READY, CONNECTING, UNREACHABLE, NO_STANDARD, NO_SKU})

# Human-readable labels for the Pad status UI (§4/§6.1). English keys; the Pad
# localizes. Kept here so Server and Pad agree on the state vocabulary.
READINESS_LABELS = {
    READY: "Jetson connected & ready",
    CONNECTING: "Jetson connecting...",
    UNREACHABLE: "Jetson unreachable — offline mode",
    NO_STANDARD: "No standard installed",
    NO_SKU: "No SKU selected",
}

# States in which an inspection may be submitted (only fully ready).
SUBMITTABLE_STATES = frozenset({READY})

# ── Per-detection-point inference result (§4) ────────────────────────────────
RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_UNCERTAIN = "uncertain"
INFERENCE_RESULTS = frozenset({RESULT_PASS, RESULT_FAIL, RESULT_UNCERTAIN})

# ── Pairing audit event types ────────────────────────────────────────────────
EVENT_PROVISIONED = "provisioned"
EVENT_PAIRED = "paired"
EVENT_REPAIRED = "repaired"
EVENT_UNPAIRED = "unpaired"
EVENT_HEALTH = "health_reported"
