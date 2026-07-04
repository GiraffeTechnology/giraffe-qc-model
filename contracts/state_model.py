"""Shared standard-lifecycle state model (PRD §10).

Session 0 — Foundation & Contracts. This is the *single source of truth* for
the standard lifecycle states used by both the Web admin studio and the Android
Pad. Do not redefine these strings anywhere else — import from here (Web) or
from the mirrored ``contracts/kotlin/StandardState.kt`` (Android).

The wire value (``value``) is the canonical serialized form used in every API
payload, bundle manifest, and SQLite row. The ``display`` name is the
English label from PRD §10 (localize via the i18n seam, never hard-code).
"""
from __future__ import annotations

from enum import Enum


class StandardState(str, Enum):
    """Lifecycle states of a SKU standard (PRD §10).

    Ordering follows the authoring → publish → on-device happy path. States are
    serialized by their ``value`` (snake_case); the English display label lives
    in :data:`STATE_DISPLAY`.
    """

    DRAFT = "draft"
    NEEDS_INFORMATION = "needs_information"
    READY_FOR_REVIEW = "ready_for_review"
    CONFIRMED = "confirmed"
    PUBLISHED = "published"
    INSTALLED_ON_PAD = "installed_on_pad"
    # Probation (试用期): a newly installed standard runs real production jobs
    # under mandatory human confirmation until it proves it can run solo
    # (≥30 jobs, ≥90% AI/human agreement). See PRD "QC Standard Authoring
    # Extension" §3. Inserted between INSTALLED_ON_PAD and ACTIVE_INSPECTION.
    PROBATION = "probation"
    ACTIVE_INSPECTION = "active_inspection"
    NEEDS_REQUALIFICATION = "needs_requalification"


# English source labels (PRD §10). Localize through the i18n seam; these are the
# canonical en-US strings, keyed identically in contracts/i18n/en.json.
STATE_DISPLAY: dict[StandardState, str] = {
    StandardState.DRAFT: "Draft",
    StandardState.NEEDS_INFORMATION: "Needs Information",
    StandardState.READY_FOR_REVIEW: "Ready for Review",
    StandardState.CONFIRMED: "Confirmed",
    StandardState.PUBLISHED: "Published",
    StandardState.INSTALLED_ON_PAD: "Installed on Pad",
    StandardState.PROBATION: "Probation",
    StandardState.ACTIVE_INSPECTION: "Active Inspection",
    StandardState.NEEDS_REQUALIFICATION: "Needs Requalification",
}

# i18n key for each state's display label (see contracts/i18n/en.json).
STATE_I18N_KEY: dict[StandardState, str] = {
    s: f"state.{s.value}" for s in StandardState
}


# Allowed forward transitions (PRD §10). Any transition not listed here is
# rejected fail-closed. Server-side authoring lives on the Web side up to
# PUBLISHED; INSTALLED_ON_PAD onward is driven by the Android Pad reporting back.
ALLOWED_TRANSITIONS: dict[StandardState, frozenset[StandardState]] = {
    StandardState.DRAFT: frozenset(
        {StandardState.NEEDS_INFORMATION, StandardState.READY_FOR_REVIEW}
    ),
    StandardState.NEEDS_INFORMATION: frozenset(
        {StandardState.DRAFT, StandardState.READY_FOR_REVIEW}
    ),
    StandardState.READY_FOR_REVIEW: frozenset(
        {StandardState.CONFIRMED, StandardState.NEEDS_INFORMATION}
    ),
    # Confirmed can be published, or bounced back for more info.
    StandardState.CONFIRMED: frozenset(
        {StandardState.PUBLISHED, StandardState.NEEDS_INFORMATION}
    ),
    # Published standards are packaged into a bundle and installed on a Pad.
    StandardState.PUBLISHED: frozenset(
        {StandardState.INSTALLED_ON_PAD, StandardState.NEEDS_REQUALIFICATION}
    ),
    # A newly installed standard enters Probation, not Active Inspection
    # directly (PRD Authoring Extension §3.1). It may also be bounced to
    # requalification on a false-pass incident before it ever runs.
    StandardState.INSTALLED_ON_PAD: frozenset(
        {StandardState.PROBATION, StandardState.NEEDS_REQUALIFICATION}
    ),
    # Probation graduates to solo Active Inspection once the qualification
    # gate is met (§3.3); a false-pass incident sends it to requalification.
    StandardState.PROBATION: frozenset(
        {StandardState.ACTIVE_INSPECTION, StandardState.NEEDS_REQUALIFICATION}
    ),
    StandardState.ACTIVE_INSPECTION: frozenset(
        {StandardState.NEEDS_REQUALIFICATION}
    ),
    # Requalification loops back into authoring (§9 false-pass response).
    StandardState.NEEDS_REQUALIFICATION: frozenset(
        {StandardState.DRAFT, StandardState.READY_FOR_REVIEW}
    ),
}


def can_transition(src: StandardState, dst: StandardState) -> bool:
    """True if ``src`` -> ``dst`` is an allowed lifecycle transition."""
    return dst in ALLOWED_TRANSITIONS.get(src, frozenset())


__all__ = [
    "StandardState",
    "STATE_DISPLAY",
    "STATE_I18N_KEY",
    "ALLOWED_TRANSITIONS",
    "can_transition",
]
