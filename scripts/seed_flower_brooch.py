#!/usr/bin/env python
"""Seed FLOWER-BROOCH-001 QC standard v1.0.

Usage:
    python scripts/seed_flower_brooch.py

Environment variables:
    QC_DB_URL  — SQLAlchemy DB URL (default: sqlite:///./giraffe_qc.db)

Idempotent: skips creation if SKU or standard version already exist.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base
import src.db.qc_models  # noqa: F401
import src.db.qc_checkpoint_models  # noqa: F401
from src.db.qc_checkpoint_models import (
    QCProductSku, QCStandardVersion, QCCheckPoint, QCCheckRule,
    QCMediaAsset, QCStandardMedia
)


CHECKPOINTS = [
    {
        "code": "STAMEN_CENTERING",
        "name": "Stamen Centering",
        "target_part": "flower_center_stamen_cluster",
        "inspection_method": "alignment",
        "severity": "major",
        "pass_rule_text": (
            "The stamen cluster must be visually centered within the four-petal flower "
            "silhouette. If the cluster is obviously shifted left, right, upward, or "
            "downward and causes visual imbalance, the item fails."
        ),
        "rule_json": {
            "required_observed_fields": [
                "flower_silhouette_center",
                "stamen_cluster_center",
                "offset_direction",
                "offset_level",
            ]
        },
        "check_rule": {
            "rule_type": "position",
            "expected_value_json": {"offset_level": "none"},
            "fail_condition_json": {"offset_level": ["obvious", "severe"]},
        },
    },
    {
        "code": "PEARL_COUNT",
        "name": "Pearl Count",
        "target_part": "stamen_pearls",
        "inspection_method": "counting",
        "severity": "critical",
        "pass_rule_text": (
            "The item must have exactly 3 visible pearls. "
            "Missing, extra, cracked, or detached pearls must be reported."
        ),
        "rule_json": None,
        "check_rule": {
            "rule_type": "count",
            "expected_value_json": {"pearl_count": 3},
            "fail_condition_json": {
                "missing_component": True,
                "extra_component": True,
                "obvious_displacement": True,
            },
        },
    },
    {
        "code": "RHINESTONE_COUNT",
        "name": "Rhinestone Count",
        "target_part": "stamen_rhinestones",
        "inspection_method": "counting",
        "severity": "critical",
        "pass_rule_text": (
            "The item must have exactly 8 rhinestones. "
            "Missing, extra, detached, or obviously displaced rhinestones must be reported."
        ),
        "rule_json": None,
        "check_rule": {
            "rule_type": "count",
            "expected_value_json": {"rhinestone_count": 8},
            "fail_condition_json": {
                "missing_component": True,
                "extra_component": True,
                "obvious_displacement": True,
            },
        },
    },
    {
        "code": "PETAL_INTEGRITY",
        "name": "Petal Integrity",
        "target_part": "four_translucent_petals",
        "inspection_method": "defect_detection",
        "severity": "critical",
        "pass_rule_text": (
            "All petals must be free from visible cracks, missing pieces, "
            "broken edges, or structural damage."
        ),
        "rule_json": {
            "required_petal_observations": [
                "petal_1_top_left",
                "petal_2_top_right",
                "petal_3_bottom_right",
                "petal_4_bottom_left",
            ]
        },
        "check_rule": {
            "rule_type": "defect",
            "expected_value_json": {"all_petals": "intact"},
            "fail_condition_json": {
                "crack_detected": True,
                "missing_piece": True,
                "broken_edge": True,
                "structural_damage": True,
            },
        },
    },
]


def seed(db) -> None:
    # SKU
    sku = db.query(QCProductSku).filter_by(sku_code="FLOWER-BROOCH-001").first()
    if not sku:
        sku = QCProductSku(
            sku_code="FLOWER-BROOCH-001",
            product_name="Pearl Rhinestone Artificial Flower Brooch",
            category="artificial_flower_accessory",
            status="active",
        )
        db.add(sku)
        db.flush()
        print(f"Created SKU: {sku.sku_code} (id={sku.id})")
    else:
        print(f"SKU already exists: {sku.sku_code} (id={sku.id})")

    # Standard version
    version = (
        db.query(QCStandardVersion)
        .filter_by(sku_id=sku.id, version_no="v1.0")
        .first()
    )
    if version:
        print(f"Standard version v1.0 already exists (id={version.id}). Skipping.")
        db.commit()
        return

    version = QCStandardVersion(
        sku_id=sku.id,
        version_no="v1.0",
        standard_name="Pearl Rhinestone Artificial Flower Brooch - v1.0",
        standard_status="active",
        approved_by="seed_script",
        approved_at=datetime.now(timezone.utc),
        effective_from=datetime.now(timezone.utc),
    )
    db.add(version)
    db.flush()
    print(f"Created standard version v1.0 (id={version.id})")

    # Placeholder reference photo
    asset = QCMediaAsset(
        media_type="image",
        media_role="standard_photo",
        storage_uri="seed://flower-brooch-001/reference_front.jpg",
        sha256=None,
    )
    db.add(asset)
    db.flush()

    db.add(QCStandardMedia(
        standard_version_id=version.id,
        media_asset_id=asset.id,
        view_type="front",
        is_primary=True,
        description="Front-view reference photo",
    ))

    # Checkpoints + rules
    for i, cp_data in enumerate(CHECKPOINTS, start=1):
        checkpoint = QCCheckPoint(
            standard_version_id=version.id,
            checkpoint_code=cp_data["code"],
            checkpoint_name=cp_data["name"],
            target_part=cp_data["target_part"],
            inspection_method=cp_data["inspection_method"],
            severity=cp_data["severity"],
            pass_rule_text=cp_data["pass_rule_text"],
            rule_json=cp_data.get("rule_json"),
            display_order=i,
        )
        db.add(checkpoint)
        db.flush()
        print(f"  Created checkpoint: {checkpoint.checkpoint_code} (id={checkpoint.id})")

        rule_data = cp_data["check_rule"]
        db.add(QCCheckRule(
            checkpoint_id=checkpoint.id,
            rule_type=rule_data["rule_type"],
            expected_value_json=rule_data.get("expected_value_json"),
            fail_condition_json=rule_data.get("fail_condition_json"),
        ))

    db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    url = os.getenv("QC_DB_URL", "sqlite:///./giraffe_qc.db")
    engine = create_engine(url, connect_args={"check_same_thread": False} if "sqlite" in url else {})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        seed(db)
