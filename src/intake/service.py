"""QC Standard Intake service — adapter-neutral intake pipeline."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.intake_models import QCIntakeMedia, QCOperatorConfirmation, QCStandardIntake
from src.db.sku_models import QCDetectionPoint, QCSkuItem, QCSkuStandardRevision
from src.inspection.service import (
    confirm_standard_revision,
    create_standard_revision,
)
from src.qc_model.studio.analysis_config import normalize_analysis_config

_PARSER_VERSION = "deterministic-v1"


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Intake creation ───────────────────────────────────────────────────────────


def create_standard_intake(
    db: Session,
    sku_id: str,
    tenant_id: str,
    raw_text: str,
    source_type: str = "api",
    source_channel: Optional[str] = None,
    source_message_id: Optional[str] = None,
    operator_id: Optional[str] = None,
) -> QCStandardIntake:
    """Create a new standard intake session from raw operator text.

    Raises ValueError if the SKU does not exist.
    """
    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise ValueError(f"SKU {sku_id!r} not found for tenant {tenant_id!r}.")

    intake = QCStandardIntake(
        id=_uid(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        source_type=source_type,
        source_channel=source_channel,
        source_message_id=source_message_id,
        operator_id=operator_id,
        raw_text=raw_text,
        status="received",
    )
    db.add(intake)
    db.commit()
    db.refresh(intake)
    return intake


def attach_intake_media(
    db: Session,
    intake_id: str,
    media_type: str = "image",
    media_role: str = "standard_photo",
    image_url: Optional[str] = None,
    local_path: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    sha256: Optional[str] = None,
    mime_type: Optional[str] = None,
    width_px: Optional[int] = None,
    height_px: Optional[int] = None,
    duration_ms: Optional[int] = None,
    metadata_json: Optional[dict] = None,
    tenant_id: Optional[str] = None,
) -> QCIntakeMedia:
    """Attach a media file to an existing intake session."""
    intake = db.query(QCStandardIntake).filter_by(id=intake_id).one()
    tid = tenant_id or intake.tenant_id

    media = QCIntakeMedia(
        id=_uid(),
        tenant_id=tid,
        intake_id=intake_id,
        media_type=media_type,
        media_role=media_role,
        image_url=image_url,
        local_path=local_path,
        thumbnail_url=thumbnail_url,
        sha256=sha256,
        mime_type=mime_type,
        width_px=width_px,
        height_px=height_px,
        duration_ms=duration_ms,
        metadata_json=metadata_json,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


# ── Extraction ────────────────────────────────────────────────────────────────


def extract_standard_draft(
    db: Session,
    intake_id: str,
) -> QCStandardIntake:
    """Parse raw_text into a structured extraction draft (deterministic, no LLM).

    Sets status to 'pending_confirmation' and persists extracted_json and
    confirmation_payload_json.  Does NOT create any standard revision.
    """
    intake = db.query(QCStandardIntake).filter_by(id=intake_id).one()
    if not intake.raw_text:
        raise ValueError(f"Intake {intake_id!r} has no raw_text to extract from.")

    sku = db.query(QCSkuItem).filter_by(id=intake.sku_id).one()
    extracted = _deterministic_parse(intake.raw_text, sku)

    # confirmation_payload_json mirrors extracted_json for operator review
    confirmation_payload = {
        "sku_id": intake.sku_id,
        "checkpoints": extracted["checkpoints"],
        "questions_for_operator": extracted["questions_for_operator"],
    }

    intake.extracted_json = extracted
    intake.confirmation_payload_json = confirmation_payload
    intake.status = "pending_confirmation"
    intake.parser_version = _PARSER_VERSION
    intake.confidence_score = _score(extracted)
    db.commit()
    db.refresh(intake)
    return intake


def persist_structured_draft(
    db: Session,
    intake_id: str,
    *,
    checkpoints: list[dict],
    questions: list[dict],
    parser_version: str,
) -> QCStandardIntake:
    """Persist a model-produced draft for explicit human confirmation.

    This is intentionally separate from the deterministic test adapter.  It
    never creates a standard revision and therefore cannot bypass the Admin
    Studio confirmation gate.

    UI audit (2026-07-22): a draft with no checkpoints (e.g. a photo-analysis
    turn that only asks clarifying questions) has nothing for the admin to
    confirm or reject. Marking it ``pending_confirmation`` anyway left it
    permanently pending — ``sku_summary()``'s "most recent pending
    confirmation" lookup would later resurface it as an empty confirm card
    on an unrelated page load. Such a draft is recorded as ``extracted``
    instead, so it never surfaces as a confirmable candidate.
    """
    intake = db.query(QCStandardIntake).filter_by(id=intake_id).one()
    extracted = {
        "sku_id": intake.sku_id,
        "checkpoints": checkpoints,
        "questions_for_operator": questions,
    }
    intake.extracted_json = extracted
    intake.confirmation_payload_json = {
        "sku_id": intake.sku_id,
        "checkpoints": checkpoints,
        "questions_for_operator": questions,
    }
    intake.status = "pending_confirmation" if checkpoints else "extracted"
    intake.parser_version = parser_version[:64]
    intake.confidence_score = _score(extracted)
    db.commit()
    db.refresh(intake)
    return intake


def _score(extracted: dict) -> float:
    """Rough confidence score: fraction of checkpoints with no open questions."""
    n = len(extracted.get("checkpoints", []))
    q = len(extracted.get("questions_for_operator", []))
    if n == 0:
        return 0.0
    return max(0.0, 1.0 - q / n)


def _deterministic_parse(raw_text: str, sku: QCSkuItem) -> dict:
    """Simple keyword-driven checkpoint extractor — no LLM required."""
    text = raw_text.lower()
    checkpoints = []
    questions: list[dict] = []
    order = 1

    # --- counting checkpoints ---
    count_patterns = [
        (r"pearl[s]?\s+count\s+(\d+)", "PEARL_COUNT", "Pearl Count",
         "Count of pearls must match expected value.", "counting", "critical"),
        (r"rhinestone[s]?\s+count\s+(\d+)", "RHINESTONE_COUNT", "Rhinestone Count",
         "Count of rhinestones must match expected value.", "counting", "critical"),
        (r"button[s]?\s+count\s+(\d+)", "BUTTON_COUNT", "Button Count",
         "Button count must match expected value.", "counting", "critical"),
        (r"hole[s]?\s+count\s+(\d+)", "HOLE_COUNT", "Hole Count",
         "Number of holes must match expected value.", "counting", "critical"),
        (r"barcode[s]?\s+count\s+(\d+)", "BARCODE_COUNT", "Barcode Count",
         "Barcode count must match expected value.", "counting", "critical"),
    ]
    for pattern, code, label, criteria, method, severity in count_patterns:
        m = re.search(pattern, text)
        if m:
            checkpoints.append({
                "point_code": code, "label": label, "description": criteria,
                "method_hint": method, "severity": severity,
                "expected_value": m.group(1), "pass_criteria": criteria,
            })
            order += 1

    # --- presence/alignment/integrity checkpoints ---
    kw_checkpoints = [
        (["center align", "centering", "alignment", "center"], "STAMEN_CENTERING",
         "Stamen Centering", "The stamen cluster should be visually centered.",
         "alignment", "major",
         "Stamen cluster must be visually centered within the flower silhouette."),
        (["petal crack", "petal integrity", "petal"], "PETAL_INTEGRITY",
         "Petal Integrity", "No petals may be bent, cracked, or missing.",
         "defect_detection", "critical", "All petals must be intact."),
        (["collar stitch", "collar seam", "collar"], "COLLAR_STITCHING",
         "Collar Stitching", "Collar stitching must be even with no loose threads.",
         "defect_detection", "major", "No visible stitching defects on collar."),
        (["fabric stain", "stain"], "FABRIC_STAIN",
         "Fabric Stain", "No visible stains on fabric surface.",
         "defect_detection", "major", "Fabric surface must be stain-free."),
        (["label position", "label"], "LABEL_POSITION",
         "Label Position", "Label must be placed at the specified location.",
         "alignment", "minor", "Label must be within tolerance of specified position."),
        (["surface scratch", "scratch"], "SURFACE_SCRATCH",
         "Surface Scratch", "No scratches on the visible surface.",
         "defect_detection", "major", "Surface must be scratch-free."),
        (["edge burr", "burr"], "EDGE_BURR",
         "Edge Burr", "No burrs on machined edges.",
         "defect_detection", "major", "All edges must be deburr-processed."),
        (["deformation", "shape"], "DEFORMATION_CHECK",
         "Deformation Check", "Part must not be bent or deformed.",
         "shape_compare", "critical", "Shape must match reference template."),
        (["barcode present", "barcode"], "BARCODE_PRESENT",
         "Barcode Present", "A readable barcode must be present.",
         "presence_check", "critical", "Barcode must be present and scannable."),
        (["barcode readable", "readable"], "BARCODE_READABLE",
         "Barcode Readable", "The barcode must scan correctly.",
         "readability_check", "critical", "Barcode must return valid scan result."),
        (["carton damage", "carton"], "CARTON_DAMAGE",
         "Carton Damage", "No physical damage to carton.",
         "defect_detection", "major", "Carton must show no dents, tears, or crush damage."),
        (["seal integrity", "seal"], "SEAL_INTEGRITY",
         "Seal Integrity", "Seals must be intact.",
         "defect_detection", "major", "All seals must be unbroken."),
    ]

    existing_codes = {c["point_code"] for c in checkpoints}
    for keywords, code, label, desc, method, severity, criteria in kw_checkpoints:
        if code in existing_codes:
            continue
        if any(kw in text for kw in keywords):
            checkpoints.append({
                "point_code": code, "label": label, "description": desc,
                "method_hint": method, "severity": severity,
                "expected_value": None, "pass_criteria": criteria,
            })
            existing_codes.add(code)
            order += 1

    # Raise open questions for missing expected_value on counting checkpoints
    for cp in checkpoints:
        if cp["method_hint"] == "counting" and not cp["expected_value"]:
            questions.append({
                "field": f"{cp['point_code']}.expected_value",
                "question": f"Please confirm the expected count for {cp['label']}.",
            })

    return {
        "sku_id": sku.id,
        "product_category": sku.category or "general",
        "standard_name": f"QC Standard Draft — {sku.name}",
        "checkpoints": checkpoints,
        "questions_for_operator": questions,
    }


# ── Confirmation ──────────────────────────────────────────────────────────────


def confirm_standard_intake(
    db: Session,
    intake_id: str,
    confirmed_by: str,
    confirmed_checkpoints: list[dict],
    operator_comment: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> tuple[QCSkuStandardRevision, QCOperatorConfirmation]:
    """Confirm the extracted draft, creating an active standard revision.

    confirmed_checkpoints is the operator's final list — same schema as
    extracted_json['checkpoints'] but with any corrections applied.

    Returns (active_revision, confirmation_record).
    """
    intake = db.query(QCStandardIntake).filter_by(id=intake_id).one()
    tid = tenant_id or intake.tenant_id

    if intake.status not in ("pending_confirmation", "extracted"):
        raise ValueError(
            f"Intake {intake_id!r} has status {intake.status!r}; "
            "must be pending_confirmation to confirm."
        )
    if not confirmed_checkpoints:
        raise ValueError("confirmed_checkpoints must not be empty.")

    # Detect duplicate point_codes before creating anything
    seen_codes: set[str] = set()
    for i, cp in enumerate(confirmed_checkpoints):
        code = cp.get("point_code", "").strip().upper()
        if code in seen_codes:
            raise ValueError(
                f"Duplicate point_code {code!r} in confirmed_checkpoints. "
                "Each checkpoint code must be unique within a standard revision."
            )
        if code:
            seen_codes.add(code)

    # Create a new draft revision via the domain service
    revision = create_standard_revision(
        db,
        sku_id=intake.sku_id,
        tenant_id=tid,
        created_from="intake",
        actor=confirmed_by,
        reason=operator_comment or "Operator confirmed via intake",
    )

    # Create detection points from confirmed checkpoints
    for i, cp in enumerate(confirmed_checkpoints):
        point_code = cp.get("point_code", "").strip().upper()
        if not point_code:
            raise ValueError(f"Checkpoint at index {i} has no point_code.")
        try:
            expected_features, cv_config = normalize_analysis_config(
                cp.get("expected_features"), cp.get("cv_config"),
            )
        except ValueError as exc:
            raise ValueError(
                f"Checkpoint {point_code!r} has invalid CV analysis config: {exc}"
            ) from exc
        dp = QCDetectionPoint(
            id=_uid(),
            tenant_id=tid,
            sku_id=intake.sku_id,
            standard_revision_id=revision.id,
            point_code=point_code,
            label=cp.get("label", point_code),
            description=cp.get("description"),
            method_hint=cp.get("method_hint"),
            severity=cp.get("severity", "major"),
            expected_value=cp.get("expected_value"),
            pass_criteria=cp.get("pass_criteria"),
            expected_features_json=expected_features,
            cv_config_json=cv_config,
            sort_order=i + 1,
            is_active=True,
        )
        db.add(dp)
    db.flush()

    # Activate the revision (archives prior active one)
    active_revision = confirm_standard_revision(
        db,
        revision_id=revision.id,
        confirmed_by=confirmed_by,
        tenant_id=tid,
    )

    # Persist confirmation record
    conf = QCOperatorConfirmation(
        id=_uid(),
        tenant_id=tid,
        intake_id=intake_id,
        sku_id=intake.sku_id,
        status="confirmed",
        confirmed_by=confirmed_by,
        confirmed_json={"checkpoints": confirmed_checkpoints},
        operator_comment=operator_comment,
        created_standard_revision_id=active_revision.id,
        confirmed_at=_now(),
    )
    db.add(conf)

    intake.status = "confirmed"
    db.commit()
    db.refresh(active_revision)
    db.refresh(conf)
    return active_revision, conf


def reject_standard_intake(
    db: Session,
    intake_id: str,
    rejected_by: str,
    reason: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> QCStandardIntake:
    """Reject an intake session without creating any standard revision."""
    intake = db.query(QCStandardIntake).filter_by(id=intake_id).one()
    tid = tenant_id or intake.tenant_id

    conf = QCOperatorConfirmation(
        id=_uid(),
        tenant_id=tid,
        intake_id=intake_id,
        sku_id=intake.sku_id,
        status="rejected",
        confirmed_by=rejected_by,
        operator_comment=reason,
        confirmed_at=_now(),
    )
    db.add(conf)
    intake.status = "rejected"
    db.commit()
    db.refresh(intake)
    return intake
