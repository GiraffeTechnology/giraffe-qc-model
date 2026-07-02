"""Qualification harness, shadow mode, and accuracy gate service (PR 27).

Runs the production-eligible VLM against human-labeled samples, computes per
detection-point confusion metrics + false-pass/false-fail rates, and produces a
qualification report. Only a supervisor-approved report that meets the
thresholds unlocks L3 ``controlled_active`` (consulted by the readiness gate).

Fail-closed throughout: false pass is critical (default max = 0); a report is
immutable once approved; qualification runs are server-side + production-eligible
only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.qc_qualification_models import (
    APPROVAL_APPROVED,
    LABEL_FAIL,
    LABEL_PASS,
    REPORT_APPROVED,
    REPORT_DRAFT,
    REPORT_REJECTED,
    VALID_APPROVAL_DECISIONS,
    VALID_LABELS,
    QualificationApproval,
    QualificationDataset,
    QualificationReport,
    QualificationResult,
    QualificationRun,
    QualificationSample,
    ShadowObservation,
)
from src.db.qc_sample_learning_models import QCConfirmedVisualRule
from src.db.qc_production_models import (
    DISPOSITION_PASS,
    DISPOSITION_REJECT,
)
from src.qc_model.production.provider import (
    DetectionInspectionRequest,
    ProductionInspectionProvider,
    ProductionProviderError,
    ProductionProviderNotConfigured,
    get_production_inspection_provider,
    is_production_eligible_provider,
)
from src.qc_model.production.runtime import assert_server_side_runtime
from src.qc_model.qualification.thresholds import get_l3_thresholds
from src.qc_model.training_pack.ownership import assert_pack_accessible
from src.qc_model.sample_learning.types import is_valid_sample_type


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DatasetNotFound(ValueError):
    pass


class RunNotFound(ValueError):
    pass


class ReportNotFound(ValueError):
    pass


class InvalidSample(ValueError):
    pass


class ProviderNotEligible(ValueError):
    pass


class QualificationRunFailed(ValueError):
    pass


class ReportImmutable(ValueError):
    """An approved qualification report cannot be changed."""


class InvalidApproval(ValueError):
    pass


# ── Datasets + samples ───────────────────────────────────────────────────────


def create_dataset(
    db: Session, training_pack_id: str, tenant_id: str = "default",
    sku_id: Optional[str] = None, station_id: Optional[str] = None,
    name: Optional[str] = None, created_by: Optional[str] = None,
) -> QualificationDataset:
    assert_pack_accessible(db, training_pack_id, tenant_id)
    ds = QualificationDataset(
        id=_uid(), tenant_id=tenant_id, training_pack_id=training_pack_id,
        sku_id=sku_id, station_id=station_id, name=name, created_by=created_by,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def get_dataset(db: Session, dataset_id: str, tenant_id: str = "default") -> QualificationDataset:
    ds = db.query(QualificationDataset).filter_by(id=dataset_id, tenant_id=tenant_id).first()
    if ds is None:
        raise DatasetNotFound(f"Qualification dataset {dataset_id!r} not found")
    return ds


def add_sample(
    db: Session, dataset_id: str, detection_point_code: str, sample_type: str,
    image_reference: str, human_label: str, tenant_id: str = "default",
    metadata: Optional[dict] = None,
) -> QualificationSample:
    ds = get_dataset(db, dataset_id, tenant_id)
    if human_label not in VALID_LABELS:
        raise InvalidSample(f"human_label must be one of {sorted(VALID_LABELS)}, got {human_label!r}")
    if not is_valid_sample_type(sample_type):
        raise InvalidSample(f"invalid sample_type: {sample_type!r}")
    if not image_reference:
        raise InvalidSample("image_reference is required")
    sample = QualificationSample(
        id=_uid(), tenant_id=tenant_id, dataset_id=ds.id, training_pack_id=ds.training_pack_id,
        detection_point_code=detection_point_code, sample_type=sample_type,
        image_reference=image_reference, human_label=human_label, metadata_json=metadata or {},
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return sample


# ── Prediction mapping ───────────────────────────────────────────────────────


def _predicted_label(disposition: str) -> str:
    """Map a model recommendation to pass / fail / indeterminate."""
    if disposition == DISPOSITION_PASS:
        return "pass"
    if disposition == DISPOSITION_REJECT:
        return "fail"
    # review_required / capture_retry_required / measurement_required → escalate.
    return "indeterminate"


# ── Qualification run ────────────────────────────────────────────────────────


def run_qualification(
    db: Session, dataset_id: str, tenant_id: str = "default",
    provider: Optional[ProductionInspectionProvider] = None,
) -> QualificationRun:
    ds = get_dataset(db, dataset_id, tenant_id)

    # Server-side + production-eligible provider only.
    assert_server_side_runtime()
    provider = provider or get_production_inspection_provider()
    if not getattr(provider, "is_configured", True):
        raise ProductionProviderNotConfigured("production_provider_not_configured")
    if not getattr(provider, "production_eligible", False) or not is_production_eligible_provider(provider.provider_name):
        raise ProviderNotEligible(
            f"provider {provider.provider_name!r} is not production-eligible for qualification"
        )

    samples = (
        db.query(QualificationSample)
        .filter_by(dataset_id=ds.id, tenant_id=tenant_id)
        .order_by(QualificationSample.created_at.asc())
        .all()
    )
    run = QualificationRun(
        id=_uid(), tenant_id=tenant_id, dataset_id=ds.id, training_pack_id=ds.training_pack_id,
        provider=provider.provider_name, model=provider.model_name, status="running",
    )
    db.add(run)
    db.commit()

    if not samples:
        run.status = "failed"
        run.error_message = "no qualification samples"
        run.completed_at = _now()
        db.commit()
        db.refresh(run)
        return run

    confirmed_by_code = {
        c.detection_point_code: c
        for c in db.query(QCConfirmedVisualRule)
        .filter_by(training_pack_id=ds.training_pack_id, tenant_id=tenant_id).all()
    }

    # Group samples by detection point, run the provider per sample.
    by_code: dict[str, list[QualificationSample]] = {}
    for s in samples:
        by_code.setdefault(s.detection_point_code, []).append(s)

    thresholds = get_l3_thresholds()
    try:
        for code, code_samples in by_code.items():
            confirmed = confirmed_by_code.get(code)
            content = confirmed.content_json if confirmed else {}
            counters = {"true_pass": 0, "true_fail": 0, "false_pass": 0, "false_fail": 0, "indeterminate": 0}
            defect_n = boundary_n = 0
            for s in code_samples:
                if s.sample_type == "defect":
                    defect_n += 1
                elif s.sample_type == "boundary":
                    boundary_n += 1
                request = DetectionInspectionRequest(
                    detection_point_code=code, checkpoint_category="visual",
                    confirmed_content=content or {}, image_references=[s.image_reference],
                    capture_metadata=s.metadata_json or {},
                )
                try:
                    response = provider.inspect(request)
                except (ProductionProviderError, ProductionProviderNotConfigured) as exc:
                    raise QualificationRunFailed(str(exc)) from exc
                predicted = _predicted_label(response.disposition)
                _tally(counters, predicted, s.human_label)
            db.add(_build_result(run, ds, tenant_id, code, code_samples, counters, defect_n, boundary_n, thresholds))
    except QualificationRunFailed as exc:
        db.rollback()
        run = db.query(QualificationRun).filter_by(id=run.id).first()
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = _now()
        db.commit()
        db.refresh(run)
        return run

    run.status = "completed"
    run.completed_at = _now()
    db.flush()

    results = db.query(QualificationResult).filter_by(run_id=run.id, tenant_id=tenant_id).all()
    qualified_codes = [r.detection_point_code for r in results if r.meets_thresholds]
    overall = bool(results) and all(r.meets_thresholds for r in results)
    db.add(QualificationReport(
        id=_uid(), tenant_id=tenant_id, run_id=run.id, training_pack_id=ds.training_pack_id,
        overall_meets_thresholds=overall, qualified_detection_point_codes_json=qualified_codes,
        thresholds_json=thresholds.to_dict(),
        summary_json={
            "detection_points": [
                {"detection_point_code": r.detection_point_code, "false_pass_rate": r.false_pass_rate,
                 "false_fail_rate": r.false_fail_rate, "meets_thresholds": r.meets_thresholds,
                 "threshold_failures": r.threshold_failures_json}
                for r in results
            ],
        },
        status=REPORT_DRAFT,
    ))
    db.commit()
    db.refresh(run)
    return run


def _tally(counters: dict, predicted: str, human_label: str) -> None:
    if human_label == LABEL_FAIL:
        if predicted == "pass":
            counters["false_pass"] += 1  # critical: a defect passed
        elif predicted == "fail":
            counters["true_fail"] += 1
        else:
            counters["indeterminate"] += 1
    else:  # human_label == pass
        if predicted == "pass":
            counters["true_pass"] += 1
        elif predicted == "fail":
            counters["false_fail"] += 1
        else:
            counters["indeterminate"] += 1


def _build_result(run, ds, tenant_id, code, code_samples, counters, defect_n, boundary_n, thresholds) -> QualificationResult:
    n_fail = sum(1 for s in code_samples if s.human_label == LABEL_FAIL)
    n_pass = sum(1 for s in code_samples if s.human_label == LABEL_PASS)
    fp_rate = counters["false_pass"] / n_fail if n_fail else 0.0
    ff_rate = counters["false_fail"] / n_pass if n_pass else 0.0
    sample_count = len(code_samples)

    failures = []
    if fp_rate > thresholds.max_false_pass_rate:
        failures.append(f"false_pass_rate {fp_rate:.4f} > {thresholds.max_false_pass_rate}")
    if ff_rate > thresholds.max_false_fail_rate:
        failures.append(f"false_fail_rate {ff_rate:.4f} > {thresholds.max_false_fail_rate}")
    if sample_count < thresholds.min_samples_per_point:
        failures.append(f"sample_count {sample_count} < {thresholds.min_samples_per_point}")
    if defect_n < thresholds.min_defect_samples_per_point:
        failures.append(f"defect_samples {defect_n} < {thresholds.min_defect_samples_per_point}")
    if boundary_n < thresholds.min_boundary_samples_per_point:
        failures.append(f"boundary_samples {boundary_n} < {thresholds.min_boundary_samples_per_point}")

    return QualificationResult(
        id=_uid(), tenant_id=tenant_id, run_id=run.id, training_pack_id=ds.training_pack_id,
        detection_point_code=code, sample_count=sample_count,
        defect_sample_count=defect_n, boundary_sample_count=boundary_n,
        true_pass=counters["true_pass"], true_fail=counters["true_fail"],
        false_pass=counters["false_pass"], false_fail=counters["false_fail"],
        indeterminate=counters["indeterminate"],
        false_pass_rate=fp_rate, false_fail_rate=ff_rate,
        confusion_json=dict(counters),
        meets_thresholds=not failures, threshold_failures_json=failures,
    )


def get_run(db: Session, run_id: str, tenant_id: str = "default") -> QualificationRun:
    run = db.query(QualificationRun).filter_by(id=run_id, tenant_id=tenant_id).first()
    if run is None:
        raise RunNotFound(f"Qualification run {run_id!r} not found")
    return run


def get_report_for_run(db: Session, run_id: str, tenant_id: str = "default") -> Optional[QualificationReport]:
    get_run(db, run_id, tenant_id)
    return db.query(QualificationReport).filter_by(run_id=run_id, tenant_id=tenant_id).first()


def get_report(db: Session, report_id: str, tenant_id: str = "default") -> QualificationReport:
    r = db.query(QualificationReport).filter_by(id=report_id, tenant_id=tenant_id).first()
    if r is None:
        raise ReportNotFound(f"Qualification report {report_id!r} not found")
    return r


def list_results(db: Session, run_id: str, tenant_id: str = "default") -> list[QualificationResult]:
    get_run(db, run_id, tenant_id)
    return db.query(QualificationResult).filter_by(run_id=run_id, tenant_id=tenant_id).all()


# ── Supervisor approval (immutable after approval) ───────────────────────────


def approve_report(
    db: Session, report_id: str, decision: str, approved_by: str,
    tenant_id: str = "default", comment: str = "",
) -> QualificationApproval:
    report = get_report(db, report_id, tenant_id)
    if decision not in VALID_APPROVAL_DECISIONS:
        raise InvalidApproval(f"decision must be one of {sorted(VALID_APPROVAL_DECISIONS)}, got {decision!r}")
    if not approved_by or not approved_by.strip():
        raise InvalidApproval("qualification approval requires a supervisor identity")
    if report.status == REPORT_APPROVED:
        raise ReportImmutable(f"qualification report {report_id!r} is approved and immutable")
    # A report may only be approved if it actually meets the thresholds.
    if decision == APPROVAL_APPROVED and not report.overall_meets_thresholds:
        raise InvalidApproval("cannot approve a qualification report that does not meet thresholds")
    approval = QualificationApproval(
        id=_uid(), tenant_id=tenant_id, report_id=report.id, training_pack_id=report.training_pack_id,
        decision=decision, approved_by=approved_by, comment=comment,
    )
    db.add(approval)
    report.status = REPORT_APPROVED if decision == APPROVAL_APPROVED else REPORT_REJECTED
    db.commit()
    db.refresh(approval)
    return approval


def list_approvals(db: Session, report_id: str, tenant_id: str = "default") -> list[QualificationApproval]:
    get_report(db, report_id, tenant_id)
    return (
        db.query(QualificationApproval)
        .filter_by(report_id=report_id, tenant_id=tenant_id)
        .order_by(QualificationApproval.created_at.asc())
        .all()
    )


def has_approved_qualification(db: Session, training_pack_id: str, tenant_id: str = "default") -> bool:
    """True iff an approved, threshold-meeting qualification report exists."""
    return (
        db.query(QualificationReport)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id,
                   status=REPORT_APPROVED, overall_meets_thresholds=True)
        .first()
        is not None
    )


# ── Shadow mode (L1) — records only, never affects pass/reject ───────────────


def record_shadow_observation(
    db: Session, training_pack_id: str, model_disposition: str, human_decision: str,
    tenant_id: str = "default", detection_point_code: Optional[str] = None,
    image_reference: Optional[str] = None, provider: Optional[str] = None, model: Optional[str] = None,
) -> ShadowObservation:
    assert_pack_accessible(db, training_pack_id, tenant_id)
    agrees = _predicted_label(model_disposition) == (human_decision or "").strip().lower()
    obs = ShadowObservation(
        id=_uid(), tenant_id=tenant_id, training_pack_id=training_pack_id,
        detection_point_code=detection_point_code, image_reference=image_reference,
        model_disposition=model_disposition, human_decision=human_decision, agrees=agrees,
        provider=provider, model=model,
    )
    db.add(obs)
    db.commit()
    db.refresh(obs)
    return obs


def shadow_report(db: Session, training_pack_id: str, tenant_id: str = "default") -> dict:
    obs = db.query(ShadowObservation).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    total = len(obs)
    disagreements = sum(1 for o in obs if not o.agrees)
    return {
        "training_pack_id": training_pack_id,
        "observations": total,
        "disagreements": disagreements,
        "disagreement_rate": (disagreements / total) if total else 0.0,
    }
