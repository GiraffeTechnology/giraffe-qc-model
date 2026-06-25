"""Seed data for QC SKU catalog — used in tests and initial deployment."""
import uuid
from datetime import timezone
from datetime import datetime

from sqlalchemy.orm import Session

from src.db.sku_models import (
    QCSkuItem,
    QCSkuStandardRevision,
    QCDetectionPoint,
)


def _uid() -> str:
    return uuid.uuid4().hex


def seed_flower_brooch(db: Session, tenant_id: str = "default") -> QCSkuItem:
    """Seed FLOWER-BROOCH-001 with an active standard revision and 4 checkpoints.

    Idempotent: returns existing SKU if already present.
    """
    existing = (
        db.query(QCSkuItem)
        .filter_by(tenant_id=tenant_id, item_number="FLOWER-BROOCH-001")
        .first()
    )
    if existing is not None:
        return existing

    sku = QCSkuItem(
        id=_uid(),
        tenant_id=tenant_id,
        item_number="FLOWER-BROOCH-001",
        name="Flower Brooch",
        category="Jewelry",
        description="Hand-crafted flower brooch with pearl center and rhinestone petals.",
        status="active",
    )
    db.add(sku)
    db.flush()

    revision = QCSkuStandardRevision(
        id=_uid(),
        sku_id=sku.id,
        tenant_id=tenant_id,
        revision_no=1,
        status="active",
        created_from="seed",
        confirmed_by="system",
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(revision)
    db.flush()

    checkpoints = [
        QCDetectionPoint(
            id=_uid(),
            tenant_id=tenant_id,
            sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="STAMEN_CENTERING",
            label="Stamen Centering",
            description="Central stamen must be aligned within 2mm of geometric center.",
            severity="major",
            sort_order=1,
            is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(),
            tenant_id=tenant_id,
            sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="PEARL_COUNT",
            label="Pearl Count",
            description="Exactly 3 pearls must be present around the stamen.",
            expected_value="3",
            severity="critical",
            sort_order=2,
            is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(),
            tenant_id=tenant_id,
            sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="RHINESTONE_COUNT",
            label="Rhinestone Count",
            description="Exactly 8 rhinestones must be set in the outer petal ring.",
            expected_value="8",
            severity="critical",
            sort_order=3,
            is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(),
            tenant_id=tenant_id,
            sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="PETAL_INTEGRITY",
            label="Petal Integrity",
            description="No petals may be bent, cracked, or missing.",
            severity="critical",
            sort_order=4,
            is_active=True,
        ),
    ]
    for cp in checkpoints:
        db.add(cp)

    db.commit()
    db.refresh(sku)
    return sku


def seed_shirt_custom(db: Session, tenant_id: str = "default") -> QCSkuItem:
    """Seed SHIRT-CUSTOM-001 — garment/textile QC with 4 checkpoints.

    Idempotent: returns existing SKU if already present.
    """
    existing = (
        db.query(QCSkuItem)
        .filter_by(tenant_id=tenant_id, item_number="SHIRT-CUSTOM-001")
        .first()
    )
    if existing is not None:
        return existing

    sku = QCSkuItem(
        id=_uid(),
        tenant_id=tenant_id,
        item_number="SHIRT-CUSTOM-001",
        name="Custom Shirt",
        category="garment_textile",
        description="Custom-tailored shirt — button count, collar, fabric, and label QC.",
        status="active",
    )
    db.add(sku)
    db.flush()

    revision = QCSkuStandardRevision(
        id=_uid(),
        sku_id=sku.id,
        tenant_id=tenant_id,
        revision_no=1,
        status="active",
        created_from="seed",
        confirmed_by="system",
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(revision)
    db.flush()

    checkpoints = [
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="BUTTON_COUNT", label="Button Count",
            description="Shirt must have exactly 7 buttons.",
            method_hint="counting", expected_value="7",
            severity="critical", sort_order=1, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="COLLAR_STITCHING", label="Collar Stitching",
            description="Collar stitching must be even with no loose threads.",
            method_hint="defect_detection",
            severity="major", sort_order=2, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="FABRIC_STAIN", label="Fabric Stain",
            description="No visible stains on the fabric surface.",
            method_hint="defect_detection",
            severity="major", sort_order=3, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="LABEL_POSITION", label="Label Position",
            description="Care label must be at the inner back collar within tolerance.",
            method_hint="alignment",
            severity="minor", sort_order=4, is_active=True,
        ),
    ]
    for cp in checkpoints:
        db.add(cp)

    db.commit()
    db.refresh(sku)
    return sku


def seed_metal_bracket(db: Session, tenant_id: str = "default") -> QCSkuItem:
    """Seed METAL-BRACKET-001 — industrial component QC with 4 checkpoints.

    Idempotent: returns existing SKU if already present.
    """
    existing = (
        db.query(QCSkuItem)
        .filter_by(tenant_id=tenant_id, item_number="METAL-BRACKET-001")
        .first()
    )
    if existing is not None:
        return existing

    sku = QCSkuItem(
        id=_uid(),
        tenant_id=tenant_id,
        item_number="METAL-BRACKET-001",
        name="Metal Bracket",
        category="industrial_component",
        description="Stamped metal bracket — hole count, surface, edge, and shape QC.",
        status="active",
    )
    db.add(sku)
    db.flush()

    revision = QCSkuStandardRevision(
        id=_uid(),
        sku_id=sku.id,
        tenant_id=tenant_id,
        revision_no=1,
        status="active",
        created_from="seed",
        confirmed_by="system",
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(revision)
    db.flush()

    checkpoints = [
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="HOLE_COUNT", label="Hole Count",
            description="Bracket must have exactly 4 mounting holes.",
            method_hint="counting", expected_value="4",
            severity="critical", sort_order=1, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="SURFACE_SCRATCH", label="Surface Scratch",
            description="No scratches on the visible treated surface.",
            method_hint="defect_detection",
            severity="major", sort_order=2, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="EDGE_BURR", label="Edge Burr",
            description="No burrs on machined edges.",
            method_hint="defect_detection",
            severity="major", sort_order=3, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="DEFORMATION_CHECK", label="Deformation Check",
            description="Part must not be bent or deformed from reference template.",
            method_hint="shape_compare",
            severity="critical", sort_order=4, is_active=True,
        ),
    ]
    for cp in checkpoints:
        db.add(cp)

    db.commit()
    db.refresh(sku)
    return sku


def seed_carton_label(db: Session, tenant_id: str = "default") -> QCSkuItem:
    """Seed CARTON-LABEL-001 — packaging/label QC with 4 checkpoints.

    Idempotent: returns existing SKU if already present.
    """
    existing = (
        db.query(QCSkuItem)
        .filter_by(tenant_id=tenant_id, item_number="CARTON-LABEL-001")
        .first()
    )
    if existing is not None:
        return existing

    sku = QCSkuItem(
        id=_uid(),
        tenant_id=tenant_id,
        item_number="CARTON-LABEL-001",
        name="Carton Label",
        category="packaging_label",
        description="Retail carton — barcode presence, readability, carton damage, and seal QC.",
        status="active",
    )
    db.add(sku)
    db.flush()

    revision = QCSkuStandardRevision(
        id=_uid(),
        sku_id=sku.id,
        tenant_id=tenant_id,
        revision_no=1,
        status="active",
        created_from="seed",
        confirmed_by="system",
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(revision)
    db.flush()

    checkpoints = [
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="BARCODE_PRESENT", label="Barcode Present",
            description="A barcode label must be present on the carton.",
            method_hint="presence_check",
            severity="critical", sort_order=1, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="BARCODE_READABLE", label="Barcode Readable",
            description="The barcode must scan correctly and return a valid result.",
            method_hint="readability_check",
            severity="critical", sort_order=2, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="CARTON_DAMAGE", label="Carton Damage",
            description="No dents, tears, or crush damage on the carton.",
            method_hint="defect_detection",
            severity="major", sort_order=3, is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(), tenant_id=tenant_id, sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="SEAL_INTEGRITY", label="Seal Integrity",
            description="All seals must be unbroken and show no tamper evidence.",
            method_hint="defect_detection",
            severity="major", sort_order=4, is_active=True,
        ),
    ]
    for cp in checkpoints:
        db.add(cp)

    db.commit()
    db.refresh(sku)
    return sku


def seed_all_fixtures(db: Session, tenant_id: str = "default") -> list:
    """Seed all four QC fixture SKUs. Returns list of QCSkuItem."""
    return [
        seed_flower_brooch(db, tenant_id),
        seed_shirt_custom(db, tenant_id),
        seed_metal_bracket(db, tenant_id),
        seed_carton_label(db, tenant_id),
    ]
