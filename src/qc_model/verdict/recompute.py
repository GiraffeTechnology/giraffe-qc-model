"""Server-side verdict recomputation (§9) — the safety-critical core.

The server **never trusts** the Pad's ``overall_result``. It re-derives the
authoritative verdict from the submitted checkpoint results, evaluated against
the standard revision / bundle version the Pad actually used — never against the
latest revision.

This module is **pure**: :func:`recompute_verdict` takes a
:class:`PadSubmission` plus the :class:`StandardRevisionSpec` that was in force,
and returns a :class:`ServerVerdict`. No database, no I/O — so Session 7's
security tests can hit it directly.

## Rules (implemented exactly, §9.2)

1. A missing required checkpoint → the overall **cannot be PASS**.
2. Any non-passing checkpoint → the overall **cannot be PASS**.
3. Evaluate against the ``standard_revision_id`` / ``bundle_version`` the Pad
   used, never the latest.
4. Unknown standard revision → **fail closed** (never PASS).
5. Unsafe ``bundle_version`` mismatch → fail closed / **review-required**.

## Verdict precedence (highest wins)

    unknown standard revision           → review_required (fail-closed)
    bundle_version mismatch             → review_required (fail-closed)
    any checkpoint result == fail       → fail        (critical noted separately)
    any required checkpoint missing     → review_required
    any other non-passing checkpoint    → review_required
    all required checkpoints pass       → pass

``fail`` outranks ``missing``/``review_required``: an observed defect is a hard
fail regardless of what else is absent. But a fail can **never** be relaxed to a
pass, which is the invariant that matters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Verdict space
PASS = "pass"
FAIL = "fail"
REVIEW_REQUIRED = "review_required"

# A submitted checkpoint result counts as "passing" only if it is exactly this.
_PASSING = PASS


@dataclass(frozen=True)
class SubmittedCheckpoint:
    """One checkpoint result as claimed by the Pad."""

    checkpoint_id: str
    result: str  # pass | fail | not_visible | low_confidence | review_required | ...


@dataclass(frozen=True)
class PadSubmission:
    """What the Pad submits for a completed inspection job (§9 input shape)."""

    job_ref: str
    standard_revision_id: str
    bundle_version: str
    pad_overall_result: str
    checkpoints: tuple[SubmittedCheckpoint, ...] = ()


@dataclass(frozen=True)
class StandardRevisionSpec:
    """The authoritative definition of the revision the Pad used.

    ``known=False`` (or passing ``None`` to :func:`recompute_verdict`) means the
    server does not recognise the revision → fail closed.
    """

    revision_id: str
    bundle_version: str
    required_checkpoint_ids: frozenset[str]
    critical_checkpoint_ids: frozenset[str] = frozenset()
    known: bool = True


@dataclass
class ServerVerdict:
    """The recomputed, authoritative verdict plus the diff vs the Pad claim."""

    server_overall_result: str
    pad_overall_result: str
    agrees: bool
    rule_applied: str
    standard_revision_id: str
    bundle_version: str
    missing_checkpoints: list[str] = field(default_factory=list)
    failing_checkpoints: list[str] = field(default_factory=list)
    non_passing_checkpoints: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)
    review_required: bool = False

    def as_dict(self) -> dict:
        return {
            "server_overall_result": self.server_overall_result,
            "pad_overall_result": self.pad_overall_result,
            "agrees": self.agrees,
            "rule_applied": self.rule_applied,
            "standard_revision_id": self.standard_revision_id,
            "bundle_version": self.bundle_version,
            "missing_checkpoints": list(self.missing_checkpoints),
            "failing_checkpoints": list(self.failing_checkpoints),
            "non_passing_checkpoints": list(self.non_passing_checkpoints),
            "warnings": list(self.warnings),
            "differences": list(self.differences),
            "review_required": self.review_required,
        }


def recompute_verdict(
    submission: PadSubmission,
    spec: Optional[StandardRevisionSpec],
) -> ServerVerdict:
    """Re-derive the authoritative verdict. Fail-closed; never trusts the Pad."""
    warnings: list[str] = []

    def _finish(result: str, rule: str) -> ServerVerdict:
        differences: list[str] = []
        agrees = result == submission.pad_overall_result
        if not agrees:
            differences.append(
                f"pad={submission.pad_overall_result} server={result}"
            )
        # The safety-critical case: the Pad asserted PASS but the server did not.
        if submission.pad_overall_result == PASS and result != PASS:
            warnings.append("pad_claimed_pass_overridden")
        return ServerVerdict(
            server_overall_result=result,
            pad_overall_result=submission.pad_overall_result,
            agrees=agrees,
            rule_applied=rule,
            standard_revision_id=submission.standard_revision_id,
            bundle_version=submission.bundle_version,
            missing_checkpoints=missing,
            failing_checkpoints=failing,
            non_passing_checkpoints=non_passing,
            warnings=warnings,
            differences=differences,
            review_required=(result == REVIEW_REQUIRED),
        )

    # We compute checkpoint sets up-front so they are reported even when an
    # earlier fail-closed rule decides the overall result.
    submitted_by_id: dict[str, str] = {}
    for cp in submission.checkpoints:
        # A duplicate checkpoint id is itself suspicious — keep the worst result.
        if cp.checkpoint_id in submitted_by_id and submitted_by_id[cp.checkpoint_id] != cp.result:
            warnings.append(f"duplicate_checkpoint:{cp.checkpoint_id}")
        submitted_by_id[cp.checkpoint_id] = cp.result

    required = spec.required_checkpoint_ids if spec is not None else frozenset()
    missing = sorted(rid for rid in required if rid not in submitted_by_id)
    failing = sorted(cid for cid, res in submitted_by_id.items() if res == FAIL)
    non_passing = sorted(cid for cid, res in submitted_by_id.items() if res != _PASSING)

    # Rule 4: unknown standard revision → fail closed.
    if spec is None or not spec.known:
        warnings.append("unknown_standard_revision")
        return _finish(REVIEW_REQUIRED, "unknown_standard_revision")

    # Rule 5: bundle_version mismatch → fail closed / review-required.
    if submission.bundle_version != spec.bundle_version:
        warnings.append(
            f"bundle_version_mismatch:used={submission.bundle_version}"
            f":expected={spec.bundle_version}"
        )
        return _finish(REVIEW_REQUIRED, "bundle_version_mismatch")

    # Flag any checkpoint result the server does not understand.
    known_results = {PASS, FAIL, "not_visible", "low_confidence", REVIEW_REQUIRED, "missing"}
    for cid, res in submitted_by_id.items():
        if res not in known_results:
            warnings.append(f"unknown_checkpoint_result:{cid}={res}")

    # Rules 1 & 2, in precedence order.
    if failing:
        critical_failing = [c for c in failing if c in spec.critical_checkpoint_ids]
        if critical_failing:
            warnings.append("critical_checkpoint_failed")
        return _finish(FAIL, "checkpoint_failed")
    if missing:
        return _finish(REVIEW_REQUIRED, "missing_required_checkpoint")
    if non_passing:
        return _finish(REVIEW_REQUIRED, "non_passing_checkpoint")

    return _finish(PASS, "all_required_pass")
