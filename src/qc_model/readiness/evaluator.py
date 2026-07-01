"""Training Pack readiness evaluator (PR 24 §2, §3).

Evaluates 10 completeness checks for a training pack and derives whether it may
enter ``exam_ready`` / ``active`` / ``on_trial``.

Status rules (PR 24 §3):
- If any required check (1–6, 8–10) is incomplete → MUST NOT enter exam_ready.
- If sample coverage (check 7) is insufficient → MAY enter on_trial, MUST NOT
  enter active.

Only check 6 (unresolved questions) is waivable, per-item, by a supervisor.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal, QCLearningJob
from src.db.qc_readiness_models import WAIVABLE_CHECK_ID, QCReadinessWaiver
from src.db.qc_sample_learning_models import (
    PseudoDefectRule,
    QCConfirmedVisualRule,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
)
from src.db.qc_source_models import QCSourceDocument

# Tenant-scoped tables that reference a training pack. A pack is "known" to a
# tenant only if at least one of these has a row for (pack, tenant). This lets
# the gate fail closed for unknown or cross-tenant packs, where every
# tenant-scoped query would otherwise be vacuously empty and pass.
_PACK_OWNED_TABLES = (
    QCSourceDocument,
    QCLearningJob,
    RuleAuthoringJob,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
    QCConfirmedVisualRule,
    PseudoDefectRule,
)

# Check ids.
C_SOURCES = "source_documents_reviewed"
C_DETECTION_POINTS = "detection_points_confirmed"
C_PHYSICAL = "physical_measurement_boundaries_confirmed"
C_RULE_VERIFICATION = "rule_verification_requirements_confirmed"
C_VISUAL_RULES = "visual_rules_approved"
C_QUESTIONS = WAIVABLE_CHECK_ID  # "no_unresolved_questions"
C_COVERAGE = "sample_coverage_sufficient"
C_CONFLICTS = "no_unreviewed_conflicts"
C_HIGH_RISK_PSEUDO = "no_pending_high_risk_pseudo_defects"
C_CRITICAL_DEFECTS = "no_pending_critical_defect_rules"

# Checks that block exam_ready (all except the coverage check).
_EXAM_READY_BLOCKING = [
    C_SOURCES, C_DETECTION_POINTS, C_PHYSICAL, C_RULE_VERIFICATION, C_VISUAL_RULES,
    C_QUESTIONS, C_CONFLICTS, C_HIGH_RISK_PSEUDO, C_CRITICAL_DEFECTS,
]

_RESOLVED_PROPOSAL = {"approved", "rejected", "applied"}


@dataclass
class CheckResult:
    id: str
    title: str
    passed: bool
    waivable: bool = False
    blocking_items: list[dict] = field(default_factory=list)


@dataclass
class ReadinessResult:
    training_pack_id: str
    checks: list[CheckResult]
    exam_ready_allowed: bool
    active_allowed: bool
    on_trial_allowed: bool
    pack_known: bool = True

    def to_dict(self) -> dict:
        return {
            "training_pack_id": self.training_pack_id,
            "pack_known": self.pack_known,
            "exam_ready_allowed": self.exam_ready_allowed,
            "active_allowed": self.active_allowed,
            "on_trial_allowed": self.on_trial_allowed,
            "checks": [
                {
                    "id": c.id, "title": c.title, "passed": c.passed,
                    "waivable": c.waivable, "blocking_items": c.blocking_items,
                }
                for c in self.checks
            ],
        }


def _pack_proposals(db: Session, training_pack_id: str, tenant_id: str):
    learning_ids = [
        r[0] for r in db.query(QCLearningJob.id).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    ]
    authoring_ids = [
        r[0] for r in db.query(RuleAuthoringJob.id).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    ]
    q = db.query(QCLearnedDetectionPointProposal).filter_by(tenant_id=tenant_id)
    proposals = q.all()
    return [
        p for p in proposals
        if (p.learning_job_id in learning_ids) or (p.rule_authoring_job_id in authoring_ids)
    ]


def _min_coverage_positive() -> int:
    return int(os.getenv("QC_READINESS_MIN_POSITIVE_SAMPLES", "1"))


def _pack_known_for_tenant(db: Session, training_pack_id: str, tenant_id: str) -> bool:
    """True if this tenant owns any data referencing the pack.

    There is no central Training Pack registry table, so ownership is derived
    from tenant-scoped rows. An unknown pack — or one owned by another tenant —
    has no such rows for this tenant and must fail closed rather than pass every
    vacuous "no pending X" check.
    """
    for model in _PACK_OWNED_TABLES:
        exists = (
            db.query(model.id)
            .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id)
            .first()
        )
        if exists is not None:
            return True
    return False


def evaluate_readiness(db: Session, training_pack_id: str, tenant_id: str = "default") -> ReadinessResult:
    pack_known = _pack_known_for_tenant(db, training_pack_id, tenant_id)
    proposals = _pack_proposals(db, training_pack_id, tenant_id)
    memory = db.query(VisualRuleMemory).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    waived_keys = {
        r[0] for r in db.query(QCReadinessWaiver.item_key)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id, check_id=C_QUESTIONS).all()
    }

    checks: list[CheckResult] = []

    # 1. Source documents reviewed.
    sources = db.query(QCSourceDocument).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    unreviewed = [s for s in sources if s.status not in ("reviewed", "rejected")]
    checks.append(CheckResult(
        C_SOURCES, "Source documents reviewed", passed=not unreviewed,
        blocking_items=[{"item_key": s.id, "description": f"source {s.source_type} still {s.status}"} for s in unreviewed],
    ))

    # 2. Detection points confirmed (no proposal left pending/proposed).
    pending_dp = [p for p in proposals if p.status == "proposed"]
    checks.append(CheckResult(
        C_DETECTION_POINTS, "Detection points confirmed", passed=not pending_dp,
        blocking_items=[{"item_key": p.id, "description": f"proposal {p.proposed_code} pending"} for p in pending_dp],
    ))

    # 3. Physical-measurement boundaries confirmed.
    phys = [p for p in proposals if p.proposed_checkpoint_category == "physical_measurement"]
    phys_bad = [p for p in phys if p.status not in ("approved", "applied") or not (p.decision_rule or "").strip()]
    checks.append(CheckResult(
        C_PHYSICAL, "Physical-measurement boundaries confirmed", passed=not phys_bad,
        blocking_items=[{"item_key": p.id, "description": f"{p.proposed_code}: boundary/decision_rule not confirmed"} for p in phys_bad],
    ))

    # 4. Rule-verification requirements confirmed (approved or rejected).
    rulever = [p for p in proposals if p.proposed_checkpoint_category == "rule_verification"]
    rulever_pending = [p for p in rulever if p.status not in _RESOLVED_PROPOSAL]
    checks.append(CheckResult(
        C_RULE_VERIFICATION, "Rule-verification requirements confirmed", passed=not rulever_pending,
        blocking_items=[{"item_key": p.id, "description": f"{p.proposed_code} pending"} for p in rulever_pending],
    ))

    # 5. Visual rules approved (no VisualRuleMemory left proposed).
    pending_mem = [m for m in memory if m.status == "proposed"]
    checks.append(CheckResult(
        C_VISUAL_RULES, "Visual rule memory reviewed", passed=not pending_mem,
        blocking_items=[{"item_key": m.id, "description": f"visual rule memory {m.feature_type} pending"} for m in pending_mem],
    ))

    # 6. No unresolved questions (waivable, per item). Questions on *resolved*
    #    proposals (approved/applied) that still carry open ambiguities.
    question_items: list[dict] = []
    for p in proposals:
        if p.status in ("approved", "applied"):
            for i, q in enumerate(p.uncertainties_json or []):
                key = f"{p.id}::{i}"
                if key not in waived_keys:
                    question_items.append({"item_key": key, "description": f"{p.proposed_code}: {q}"})
    checks.append(CheckResult(
        C_QUESTIONS, "No unresolved questions/ambiguities", passed=not question_items,
        waivable=True, blocking_items=question_items,
    ))

    # 7. Sample coverage sufficient (governs on_trial vs active, provisional).
    completed_group_ids = {
        r[0] for r in db.query(SampleLearningJob.sample_group_id)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id, status="completed").all()
    }
    groups = db.query(SampleGroup).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    reviewed = [g for g in groups if g.id in completed_group_ids]
    has_positive = sum(1 for g in reviewed if g.sample_type == "positive") >= _min_coverage_positive()
    has_defect_or_boundary = any(g.sample_type in ("defect", "boundary") for g in reviewed)
    coverage_ok = has_positive and has_defect_or_boundary
    cov_blocking = []
    if not has_positive:
        cov_blocking.append({"item_key": "positive_samples", "description": "no reviewed positive sample group"})
    if not has_defect_or_boundary:
        cov_blocking.append({"item_key": "defect_boundary_samples", "description": "no reviewed defect/boundary sample group"})
    checks.append(CheckResult(
        C_COVERAGE, "Sample coverage sufficient (provisional default)", passed=coverage_ok,
        blocking_items=cov_blocking,
    ))

    # 8. No unreviewed conflicts (approved memory that would conflict with an
    #    existing confirmed rule of the same key but different content).
    confirmed = db.query(QCConfirmedVisualRule).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    confirmed_by_key = {(c.detection_point_code, c.feature_type): c for c in confirmed}
    conflicts = []
    for m in memory:
        if m.status == "approved":
            existing = confirmed_by_key.get((m.detection_point_code, m.feature_type))
            if existing is not None:
                if existing.source_memory_id != m.id and existing.content_json != _memory_content(m):
                    conflicts.append({"item_key": m.id, "description": f"approved memory conflicts with confirmed rule for {m.detection_point_code}/{m.feature_type}"})
    checks.append(CheckResult(
        C_CONFLICTS, "No unreviewed conflicts", passed=not conflicts, blocking_items=conflicts,
    ))

    # 9. No pending high-risk pseudo-defects.
    high_risk = (
        db.query(PseudoDefectRule)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id, risk_level="high", status="proposed")
        .all()
    )
    checks.append(CheckResult(
        C_HIGH_RISK_PSEUDO, "No pending high-risk pseudo-defects", passed=not high_risk,
        blocking_items=[{"item_key": r.id, "description": f"high-risk pseudo-defect: {r.pattern_text}"} for r in high_risk],
    ))

    # 10. No pending critical defect rules (critical-severity proposals still pending).
    critical_pending = [
        p for p in proposals
        if p.severity == "critical" and p.proposed_checkpoint_category == "visual_defect" and p.status == "proposed"
    ]
    checks.append(CheckResult(
        C_CRITICAL_DEFECTS, "No pending critical defect rules", passed=not critical_pending,
        blocking_items=[{"item_key": p.id, "description": f"critical defect {p.proposed_code} pending"} for p in critical_pending],
    ))

    by_id = {c.id: c for c in checks}
    # Fail closed for unknown / cross-tenant packs: a pack this tenant does not
    # own has only vacuous empty-query passes and must not be exam-ready.
    exam_ready_allowed = pack_known and all(by_id[cid].passed for cid in _EXAM_READY_BLOCKING)
    active_allowed = exam_ready_allowed and by_id[C_COVERAGE].passed
    on_trial_allowed = exam_ready_allowed
    return ReadinessResult(
        training_pack_id=training_pack_id, checks=checks,
        exam_ready_allowed=exam_ready_allowed, active_allowed=active_allowed, on_trial_allowed=on_trial_allowed,
        pack_known=pack_known,
    )


def _memory_content(m) -> dict:
    fields = [
        "normal_visual_features", "acceptable_variations", "defect_visual_features",
        "known_pseudo_defects", "capture_artifact_risks", "evidence_required",
        "review_required_conditions",
    ]
    return {f: getattr(m, f"{f}_json") or [] for f in fields}
