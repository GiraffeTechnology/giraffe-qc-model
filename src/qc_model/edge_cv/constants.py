"""Enums, allowed values, and state-transition tables for the Edge CV subsystem.

Kept as plain frozensets/dicts (not Python ``enum``) to match the lightweight,
string-typed style used across the rest of this repo's DB columns.
"""
from __future__ import annotations

# ── Device states (§9) ───────────────────────────────────────────────────────
DEVICE_UNKNOWN = "unknown"
DEVICE_REGISTERING = "registering"
DEVICE_ONLINE = "online"
DEVICE_BUSY = "busy"
DEVICE_DEGRADED = "degraded"
DEVICE_OFFLINE = "offline"
DEVICE_ERROR = "error"
DEVICE_MAINTENANCE = "maintenance"

DEVICE_STATES = frozenset(
    {
        DEVICE_UNKNOWN,
        DEVICE_REGISTERING,
        DEVICE_ONLINE,
        DEVICE_BUSY,
        DEVICE_DEGRADED,
        DEVICE_OFFLINE,
        DEVICE_ERROR,
        DEVICE_MAINTENANCE,
    }
)

# States in which a device may be selected/lease a job.
DEVICE_DISPATCHABLE_STATES = frozenset({DEVICE_ONLINE, DEVICE_DEGRADED})

# Allowed device state transitions (§9.2). Value is the set of reachable states.
DEVICE_TRANSITIONS: dict[str, frozenset[str]] = {
    DEVICE_UNKNOWN: frozenset({DEVICE_REGISTERING, DEVICE_OFFLINE}),
    DEVICE_REGISTERING: frozenset({DEVICE_ONLINE, DEVICE_ERROR, DEVICE_OFFLINE}),
    DEVICE_ONLINE: frozenset(
        {DEVICE_BUSY, DEVICE_DEGRADED, DEVICE_OFFLINE, DEVICE_MAINTENANCE, DEVICE_ERROR}
    ),
    DEVICE_BUSY: frozenset({DEVICE_ONLINE, DEVICE_DEGRADED, DEVICE_OFFLINE, DEVICE_ERROR}),
    DEVICE_DEGRADED: frozenset({DEVICE_ONLINE, DEVICE_BUSY, DEVICE_OFFLINE, DEVICE_ERROR}),
    DEVICE_OFFLINE: frozenset({DEVICE_REGISTERING, DEVICE_MAINTENANCE}),
    DEVICE_ERROR: frozenset({DEVICE_REGISTERING, DEVICE_MAINTENANCE, DEVICE_OFFLINE}),
    DEVICE_MAINTENANCE: frozenset({DEVICE_ONLINE, DEVICE_OFFLINE}),
}


def device_transition_allowed(from_status: str, to_status: str) -> bool:
    """Return True if ``from_status -> to_status`` is a permitted transition.

    A no-op transition (same state) is always allowed. Registration and offline
    detection may be reached from any state (idempotent, failure-safe).
    """
    if from_status == to_status:
        return True
    if to_status == DEVICE_OFFLINE:
        return True  # offline detection is always allowed (heartbeat TTL)
    if to_status == DEVICE_REGISTERING:
        return True  # a device may (re)register from any state
    return to_status in DEVICE_TRANSITIONS.get(from_status, frozenset())


# ── Job states (§10) ─────────────────────────────────────────────────────────
JOB_PENDING = "pending"
JOB_QUEUED = "queued"
JOB_LEASED = "leased"
JOB_RUNNING = "running"
JOB_UPLOADING = "uploading_result"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_RETRY_SCHEDULED = "retry_scheduled"
JOB_CANCELLED = "cancelled"
JOB_MANUAL_REVIEW = "manual_review_required"

JOB_STATES = frozenset(
    {
        JOB_PENDING,
        JOB_QUEUED,
        JOB_LEASED,
        JOB_RUNNING,
        JOB_UPLOADING,
        JOB_COMPLETED,
        JOB_FAILED,
        JOB_RETRY_SCHEDULED,
        JOB_CANCELLED,
        JOB_MANUAL_REVIEW,
    }
)

# Terminal job states — no further transitions expected.
JOB_TERMINAL_STATES = frozenset({JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED, JOB_MANUAL_REVIEW})

# Job states that hold a device lease and can therefore expire.
JOB_LEASED_STATES = frozenset({JOB_LEASED, JOB_RUNNING, JOB_UPLOADING})


# ── Job priority (§10) ───────────────────────────────────────────────────────
# Lower rank = higher priority. Used for numeric ordering so leasing never falls
# back to lexicographic string order (where "high" < "normal" < "low").
PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}
_DEFAULT_PRIORITY_RANK = PRIORITY_RANK["normal"]


def priority_rank(priority: str) -> int:
    return PRIORITY_RANK.get(priority, _DEFAULT_PRIORITY_RANK)


# ── Task types (§11.3) ───────────────────────────────────────────────────────
TASK_TYPES = frozenset(
    {
        "image_preprocess",
        "object_detection",
        "defect_candidate_detection",
        "color_check",
        "counting",
        "alignment_check",
        "feature_extraction",
        "ocr_optional",
    }
)

# ── Model formats (§11.3) ────────────────────────────────────────────────────
MODEL_FORMATS = frozenset(
    {"onnx", "tensorrt_engine", "torchscript", "opencv_dnn", "python_callable", "mock"}
)

# ── Result hints (§11.6) ─────────────────────────────────────────────────────
PASS_FAIL_HINTS = frozenset({"pass", "fail", "unknown", "needs_human_review"})

# ── Evidence asset types (§11.7) ─────────────────────────────────────────────
ASSET_TYPES = frozenset(
    {"input_thumbnail", "annotated_image", "crop", "mask", "heatmap", "debug_image"}
)

# ── Device types (§5.5) ──────────────────────────────────────────────────────
DEVICE_TYPE_JETSON_NANO_2GB = "jetson_nano_2gb"
DEVICE_TYPE_CPU_RUNNER = "cpu_runner"
DEVICE_TYPE_MOCK_RUNNER = "mock_runner"

# Error codes considered permanent — a failed job with one of these is not
# retried, it fails (or goes to manual review) immediately.
PERMANENT_ERROR_CODES = frozenset(
    {"model_hash_mismatch", "invalid_result_schema", "model_missing", "unsupported_task"}
)
