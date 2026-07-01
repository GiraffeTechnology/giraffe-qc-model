"""Training Pack readiness evaluator (PR 24 + Production Readiness §4).

Evaluates completeness/production checks for a training pack and derives whether
it may enter ``exam_ready`` / ``production_assisted`` (L2) / ``controlled_active``
(L3).

Production safety (Production Readiness PRD §3, §4):
- No approved/applied VisualRuleMemory ⇒ no visual QC production readiness.
- A completed sample-learning job is not enough; only supervisor-approved or
  applied visual memory counts.
- Mock/fake/stub/skeleton provider output can satisfy L0 only, never L1/L2/L3.
- Physical measurement stays record_only.
- ``controlled_active`` (L3) additionally requires a qualification report, which
  is produced by a later PR; until then L3 fails closed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal, QCLearningJob
from src.db.qc_readiness_models import WAIVABLE_CHECK_ID, QCReadinessWaiver
from src.db.qc_sample_learning_models import (
    CaptureArtifactRule,
    PseudoDefectRule,
    QCConfirmedVisualRule,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
)
from src.db.qc_source_models import QCSourceDocument
from src.qc_model.training_pack.ownership import pack_known_for_tenant

# ── Check ids ──────────────────────────────────────────────────────────────
C_SOURCES = "source_documents_reviewed"
C_DETECTION_POINTS = "detection_points_confirmed"
C_PHYSICAL = "physical_measurement_boundaries_confirmed"
C_RULE_VERIFICATION = "rule_verification_requirements_confirmed"
C_VISUAL_RULES = "visual_rules_approved"
C_VISUAL_MEMORY = "visual_rule_memory_required"
C_QUESTIONS = WAIVABLE_CHECK_ID  # "no_unresolved_questions"
C_COVERAGE = "sample_coverage_sufficient"
C_COVERAGE_L3 = "sample_coverage_sufficient_l3"
C_PROVIDER = "production_eligible_provider"
C_CONFLICTS = "no_unreviewed_conflicts"
C_HIGH_RISK_PSEUDO = "no_pending_high_risk_pseudo_defects"
C_PSEUDO_CLOSURE = "pseudo_defect_rules_closed"
C_CAPTURE_CLOSURE = "capture_artifact_rules_closed"
C_CRITICAL_DEFECTS = "no_pending_critical_defect_rules"
C_QUALIFICATION = "controlled_active_qualification"

# Knowledge-complete checks that block exam_ready.
_EXAM_READY_BLOCKING = [
    C_SOURCES, C_DETECTION_POINTS, C_PHYSICAL, C_RULE_VERIFICATION, C_VISUAL_RULES,
    C_VISUAL_MEMORY, C_QUESTIONS, C_CONFLICTS, C_HIGH_RISK_PSEUDO, C_CRITICAL_DEFECTS,
]
# Additional checks required for L2 Production Assisted mode.
_L2_BLOCKING = [C_COVERAGE, C_PROVIDER, C_PSEUDO_CLOSURE, C_CAPTURE_CLOSURE]
# Additional checks required for L3 Controlled Active mode.
_L3_BLOCKING = [C_COVERAGE_L3, C_QUALIFICATION]

_RESOLVED_PROPOSAL = {"approved", "rejected", "applied"}
_CONFIRMED_PROPOSAL = {"approved", "applied"}
_MEMORY_READY = {"approved", "applied"}

# Detection points that require visual rule memory before production readiness.
_VISUAL_CATEGORIES = {"visual_defect", "rule_verification"}
_VISUAL_AI_ROLES = {"primary_visual_judge", "information_extraction", "assisted_visual_judge"}

# Provider name substrings that can satisfy L0 only (never production readiness).
_NON_PRODUCTION_PROVIDER_MARKERS = ("mock", "fake", "stub", "skeleton")

TARGET_EXAM_READY = "exam_ready"
TARGET_PRODUCTION_ASSISTED = "production_assisted"
TARGET_CONTROLLED_ACTIVE = "controlled_active"
_VALID_TARGET_MODES = {TARGET_EXAM_READY, TARGET_PRODUCTION_ASSISTED, TARGET_CONTROLLED_ACTIVE}


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
    production_assisted_allowed: bool
    controlled_active_allowed: bool
    pack_known: bool = True
    target_mode: str = TARGET_PRODUCTION_ASSISTED

    # ── Legacy aliases (kept for backward compatibility) ────────────────────
    @property
    def active_allowed(self) -> bool:
        # ``active`` now maps to L3 Controlled Active, which requires
        # qualification — it is never a general production-safe alias.
        return self.controlled_active_allowed

    @property
    def on_trial_allowed(self) -> bool:
        # ``on_trial`` is an L1/L2 trial gate: knowledge-complete (exam_ready).
        return self.exam_ready_allowed

    def _blocking_check_ids(self) -> list[str]:
        if self.target_mode == TARGET_EXAM_READY:
            relevant = _EXAM_READY_BLOCKING
        elif self.target_mode == TARGET_CONTROLLED_ACTIVE:
            relevant = _EXAM_READY_BLOCKING + _L2_BLOCKING + _L3_BLOCKING
        else:  # production_assisted
            relevant = _EXAM_READY_BLOCKING + _L2_BLOCKING
        by_id = {c.id: c for c in self.checks}
        return [cid for cid in relevant if cid in by_id and not by_id[cid].passed]

    def to_dict(self) -> dict:
        return {
            "training_pack_id": self.training_pack_id,
            "target_mode": self.target_mode,
            "pack_known": self.pack_known,
            "exam_ready_allowed": self.exam_ready_allowed,
            "production_assisted_allowed": self.production_assisted_allowed,
            "controlled_active_allowed": self.controlled_active_allowed,
            # Legacy fields retained so existing clients keep working.
            "active_allowed": self.active_allowed,
            "on_trial_allowed": self.on_trial_allowed,
            "blocking_checks": self._blocking_check_ids(),
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
    proposals = db.query(QCLearnedDetectionPointProposal).filter_by(tenant_id=tenant_id).all()
    return [
        p for p in proposals
        if (p.learning_job_id in learning_ids) or (p.rule_authoring_job_id in authoring_ids)
    ]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _min_coverage_positive() -> int:
    return _env_int("QC_READINESS_MIN_POSITIVE_SAMPLES", 1)


def _is_non_production_provider(provider: str | None) -> bool:
    if not provider:
        return True  # no traceable provider → not production-eligible (fail closed)
    p = provider.lower()
    return any(marker in p for marker in _NON_PRODUCTION_PROVIDER_MARKERS)


def evaluate_readiness(
    db: Session,
    training_pack_id: str,
    tenant_id: str = "default",
    target_mode: str = TARGET_PRODUCTION_ASSISTED,
) -> ReadinessResult:
    if target_mode not in _VALID_TARGET_MODES:
        target_mode = TARGET_PRODUCTION_ASSISTED

    pack_known = pack_known_for_tenant(db, training_pack_id, tenant_id)
    proposals = _pack_proposals(db, training_pack_id, tenant_id)
    memory = db.query(VisualRuleMemory).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    confirmed = db.query(QCConfirmedVisualRule).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
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

    # 2. Detection points confirmed (no proposal left proposed).
    pending_dp = [p for p in proposals if p.status == "proposed"]
    checks.append(CheckResult(
        C_DETECTION_POINTS, "Detection points confirmed", passed=not pending_dp,
        blocking_items=[{"item_key": p.id, "description": f"proposal {p.proposed_code} pending"} for p in pending_dp],
    ))

    # 3. Physical-measurement boundaries confirmed (stays record_only).
    phys = [p for p in proposals if p.proposed_checkpoint_category == "physical_measurement"]
    phys_bad = [p for p in phys if p.status not in _CONFIRMED_PROPOSAL or not (p.decision_rule or "").strip()]
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

    # 5. Visual rules reviewed (no VisualRuleMemory left proposed).
    pending_mem = [m for m in memory if m.status == "proposed"]
    checks.append(CheckResult(
        C_VISUAL_RULES, "Visual rule memory reviewed", passed=not pending_mem,
        blocking_items=[{"item_key": m.id, "description": f"visual rule memory {m.feature_type} pending"} for m in pending_mem],
    ))

    # 5b. VisualRuleMemory is MANDATORY for every confirmed visual detection point
    #     (visual_defect / rule_verification with a visual AI role). §4.1.
    memory_ready_codes = {m.detection_point_code for m in memory if m.status in _MEMORY_READY}
    confirmed_codes = {c.detection_point_code for c in confirmed}
    covered_codes = memory_ready_codes | confirmed_codes
    visual_dps = [
        p for p in proposals
        if p.status in _CONFIRMED_PROPOSAL
        and p.proposed_checkpoint_category in _VISUAL_CATEGORIES
        and p.proposed_ai_role in _VISUAL_AI_ROLES
    ]
    missing_memory = [p for p in visual_dps if p.proposed_code not in covered_codes]
    checks.append(CheckResult(
        C_VISUAL_MEMORY, "Approved/applied visual rule memory for each visual detection point",
        passed=not missing_memory,
        blocking_items=[
            {"item_key": p.proposed_code, "description":
             f"visual detection point {p.proposed_code} has no approved/applied VisualRuleMemory or confirmed rule"}
            for p in missing_memory
        ],
    ))

    # 6. No unresolved questions (waivable, per item).
    question_items: list[dict] = []
    for p in proposals:
        if p.status in _CONFIRMED_PROPOSAL:
            for i, q in enumerate(p.uncertainties_json or []):
                key = f"{p.id}::{i}"
                if key not in waived_keys:
                    question_items.append({"item_key": key, "description": f"{p.proposed_code}: {q}"})
    checks.append(CheckResult(
        C_QUESTIONS, "No unresolved questions/ambiguities", passed=not question_items,
        waivable=True, blocking_items=question_items,
    ))

    # 7. Sample coverage — by type, from COMPLETED sample-learning jobs.
    completed_group_ids = {
        r[0] for r in db.query(SampleLearningJob.sample_group_id)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id, status="completed").all()
    }
    groups = db.query(SampleGroup).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    reviewed = [g for g in groups if g.id in completed_group_ids]
    counts = {t: sum(1 for g in reviewed if g.sample_type == t)
              for t in ("reference", "positive", "defect", "boundary", "capture_artifact")}

    # L2 coverage: at least 1 positive and 1 defect/boundary reviewed group.
    has_positive = counts["positive"] >= _min_coverage_positive()
    has_defect_or_boundary = (counts["defect"] + counts["boundary"]) >= 1
    cov_blocking = []
    if not has_positive:
        cov_blocking.append({"item_key": "positive_samples", "description": "no reviewed positive sample group"})
    if not has_defect_or_boundary:
        cov_blocking.append({"item_key": "defect_boundary_samples", "description": "no reviewed defect/boundary sample group"})
    checks.append(CheckResult(
        C_COVERAGE, "Sample coverage sufficient (L2)", passed=(has_positive and has_defect_or_boundary),
        blocking_items=cov_blocking,
    ))

    # 7b. L3 coverage: per-type minimums (conservative, env-configurable).
    l3_min = {
        "reference": _env_int("QC_READINESS_MIN_REFERENCE_GROUPS", 1),
        "positive": _env_int("QC_READINESS_MIN_POSITIVE_GROUPS", 2),
        "defect": _env_int("QC_READINESS_MIN_DEFECT_GROUPS", 1),
        "boundary": _env_int("QC_READINESS_MIN_BOUNDARY_GROUPS", 1),
        "capture_artifact": _env_int("QC_READINESS_MIN_CAPTURE_ARTIFACT_GROUPS", 0),
    }
    l3_cov_blocking = [
        {"item_key": f"{t}_groups", "description": f"L3 requires >= {need} reviewed {t} groups (have {counts[t]})"}
        for t, need in l3_min.items() if counts[t] < need
    ]
    checks.append(CheckResult(
        C_COVERAGE_L3, "Sample coverage sufficient (L3 controlled active)", passed=not l3_cov_blocking,
        blocking_items=l3_cov_blocking,
    ))

    # 8. Production-eligible provider — approved/applied memory must NOT trace to
    #    a mock/fake/stub/skeleton provider. §4.3.
    ready_memory = [m for m in memory if m.status in _MEMORY_READY]
    job_ids = {m.sample_learning_job_id for m in ready_memory}
    jobs = (
        db.query(SampleLearningJob).filter(SampleLearningJob.id.in_(job_ids)).all()
        if job_ids else []
    )
    provider_by_job = {j.id: j.provider for j in jobs}
    prov_blocking = []
    for m in ready_memory:
        provider = provider_by_job.get(m.sample_learning_job_id)
        if _is_non_production_provider(provider):
            prov_blocking.append({
                "item_key": m.id,
                "description": f"visual memory {m.detection_point_code or m.feature_type} traces to "
                               f"non-production provider {provider or 'unknown'}",
            })
    # Only meaningful when there is approved/applied memory to vet; when none
    # exists the visual_rule_memory_required check already blocks.
    checks.append(CheckResult(
        C_PROVIDER, "Production-eligible provider (no mock/fake/stub/skeleton)",
        passed=not prov_blocking, blocking_items=prov_blocking,
    ))

    # 9. No unreviewed conflicts (no-silent-overwrite).
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

    # 10. No pending high-risk pseudo-defects (exam_ready blocking).
    high_risk = [
        r for r in db.query(PseudoDefectRule)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id, risk_level="high", status="proposed").all()
    ]
    checks.append(CheckResult(
        C_HIGH_RISK_PSEUDO, "No pending high-risk pseudo-defects", passed=not high_risk,
        blocking_items=[{"item_key": r.id, "description": f"high-risk pseudo-defect: {r.pattern_text}"} for r in high_risk],
    ))

    # 10b/10c. Pseudo-defect / capture-artifact closure (L2/L3). §4.7.
    pending_pseudo = (
        db.query(PseudoDefectRule)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id, status="proposed").all()
    )
    checks.append(CheckResult(
        C_PSEUDO_CLOSURE, "Pseudo-defect rules reviewed/closed", passed=not pending_pseudo,
        blocking_items=[{"item_key": r.id, "description": f"pseudo-defect rule pending: {r.pattern_text}"} for r in pending_pseudo],
    ))
    pending_capture = (
        db.query(CaptureArtifactRule)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id, status="proposed").all()
    )
    checks.append(CheckResult(
        C_CAPTURE_CLOSURE, "Capture-artifact rules reviewed/closed", passed=not pending_capture,
        blocking_items=[{"item_key": r.id, "description": f"capture-artifact rule pending: {r.pattern_text}"} for r in pending_capture],
    ))

    # 11. No pending critical defect rules.
    critical_pending = [
        p for p in proposals
        if p.severity == "critical" and p.proposed_checkpoint_category == "visual_defect" and p.status == "proposed"
    ]
    checks.append(CheckResult(
        C_CRITICAL_DEFECTS, "No pending critical defect rules", passed=not critical_pending,
        blocking_items=[{"item_key": p.id, "description": f"critical defect {p.proposed_code} pending"} for p in critical_pending],
    ))

    # 12. Controlled-active qualification (L3). Produced by a later PR; until a
    #     qualification report exists, L3 fails closed.
    checks.append(CheckResult(
        C_QUALIFICATION, "Controlled-active qualification passed", passed=False,
        blocking_items=[{"item_key": "qualification_required",
                         "description": "L3 controlled active requires a passed qualification report (not yet available)"}],
    ))

    by_id = {c.id: c for c in checks}
    # Fail closed for unknown / cross-tenant packs.
    exam_ready_allowed = pack_known and all(by_id[cid].passed for cid in _EXAM_READY_BLOCKING)
    production_assisted_allowed = exam_ready_allowed and all(by_id[cid].passed for cid in _L2_BLOCKING)
    controlled_active_allowed = production_assisted_allowed and all(by_id[cid].passed for cid in _L3_BLOCKING)

    return ReadinessResult(
        training_pack_id=training_pack_id, checks=checks,
        exam_ready_allowed=exam_ready_allowed,
        production_assisted_allowed=production_assisted_allowed,
        controlled_active_allowed=controlled_active_allowed,
        pack_known=pack_known, target_mode=target_mode,
    )


def _memory_content(m) -> dict:
    fields = [
        "normal_visual_features", "acceptable_variations", "defect_visual_features",
        "known_pseudo_defects", "capture_artifact_risks", "evidence_required",
        "review_required_conditions",
    ]
    return {f: getattr(m, f"{f}_json") or [] for f in fields}
