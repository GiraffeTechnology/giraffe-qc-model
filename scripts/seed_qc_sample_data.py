#!/usr/bin/env python3
"""Seed the QC sample database with 3 SKUs for Android Pad testing.

Usage:
    uv run python scripts/seed_qc_sample_data.py

Optional env vars:
    QC_DB_URL   -- override database URL (default: sqlite:///./giraffe_qc.db)
    SEED_HOST   -- backend host for image_url (default: http://192.168.1.10:8080)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
from src.db.sku_models import (
    QCDetectionPoint,
    QCInspectionRequirement,
    QCSkuItem,
    QCStandardPhoto,
)

DB_URL = os.getenv("QC_DB_URL", "sqlite:///./giraffe_qc.db")
HOST = os.getenv("SEED_HOST", "http://192.168.1.10:8080")
TENANT = "default"


def _now() -> datetime:
    return datetime.now(timezone.utc)


SEED_DATA = [
    {
        "id": "sku-flower-001",
        "item_number": "ITEM-FLOWER-001",
        "name": "Artificial Flower A",
        "category": "artificial_flower",
        "description": "Standard inspection sample for artificial flower A",
        "photos": [
            {
                "id": "photo-flower-001-front",
                "image_url": f"{HOST}/assets/ref/sku-flower-001-front.jpg",
                "local_path": "/factory/ref/sku-flower-001-front.jpg",
                "angle": "front",
                "view_type": "standard",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "is_primary": True,
            }
        ],
        "requirements": [
            {
                "id": "req-flower-001",
                "code": "REQ-STAIN-001",
                "title": "No visible stain",
                "requirement_text": "No visible stain on front visible surface",
                "severity": "major",
                "pass_criteria": "No stain larger than 2mm on the front surface",
                "sort_order": 1,
            },
            {
                "id": "req-flower-002",
                "code": "REQ-COLOR-001",
                "title": "Flower stem color match",
                "requirement_text": "Flower stem color must match reference photo",
                "severity": "major",
                "pass_criteria": "Color deviation within 10% of reference",
                "sort_order": 2,
            },
        ],
        "detection_points": [
            {
                "id": "dp-flower-001",
                "requirement_id": "req-flower-001",
                "point_code": "DP-FLOWER-FRONT-001",
                "label": "Front surface stain check",
                "description": "Check visible front surface for stain",
                "roi_json": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                "severity": "major",
                "sort_order": 1,
            },
            {
                "id": "dp-flower-002",
                "requirement_id": "req-flower-002",
                "point_code": "DP-FLOWER-STEM-001",
                "label": "Stem color check",
                "description": "Check flower stem color against reference",
                "roi_json": {"x": 0.3, "y": 0.6, "w": 0.4, "h": 0.3},
                "severity": "major",
                "sort_order": 2,
            },
        ],
    },
    {
        "id": "sku-hairclip-001",
        "item_number": "ITEM-HAIRCLIP-001",
        "name": "Hair Clip Standard",
        "category": "accessory",
        "description": "Standard inspection sample for hair clip",
        "photos": [
            {
                "id": "photo-hairclip-001-front",
                "image_url": f"{HOST}/assets/ref/sku-hairclip-001-front.jpg",
                "local_path": "/factory/ref/sku-hairclip-001-front.jpg",
                "angle": "front",
                "view_type": "standard",
                "sha256": "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
                "is_primary": True,
            }
        ],
        "requirements": [
            {
                "id": "req-hairclip-001",
                "code": "REQ-CLIP-BENT-001",
                "title": "Metal part not bent",
                "requirement_text": "Hair clip metal part must not be bent",
                "severity": "critical",
                "pass_criteria": "No visible bending or deformation of metal clip",
                "sort_order": 1,
            },
            {
                "id": "req-hairclip-002",
                "code": "REQ-CLIP-COATING-001",
                "title": "Coating intact",
                "requirement_text": "Surface coating must be intact with no chips",
                "severity": "minor",
                "pass_criteria": "No coating chip larger than 1mm",
                "sort_order": 2,
            },
        ],
        "detection_points": [
            {
                "id": "dp-hairclip-001",
                "requirement_id": "req-hairclip-001",
                "point_code": "DP-CLIP-METAL-001",
                "label": "Metal clip deformation check",
                "description": "Check metal clip for bending or deformation",
                "roi_json": {"x": 0.2, "y": 0.2, "w": 0.6, "h": 0.6},
                "severity": "critical",
                "sort_order": 1,
            },
            {
                "id": "dp-hairclip-002",
                "requirement_id": "req-hairclip-002",
                "point_code": "DP-CLIP-SURFACE-001",
                "label": "Surface coating check",
                "description": "Check surface coating for chips or cracks",
                "roi_json": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                "severity": "minor",
                "sort_order": 2,
            },
        ],
    },
    {
        "id": "sku-bracelet-001",
        "item_number": "ITEM-BRACELET-001",
        "name": "Bracelet Standard",
        "category": "jewelry",
        "description": "Standard inspection sample for bracelet",
        "photos": [
            {
                "id": "photo-bracelet-001-front",
                "image_url": f"{HOST}/assets/ref/sku-bracelet-001-front.jpg",
                "local_path": "/factory/ref/sku-bracelet-001-front.jpg",
                "angle": "front",
                "view_type": "standard",
                "sha256": "b94d27b9934d3e08a52e52d7da7dabfac484efe04294e576b4b9ade5e0b9c148",
                "is_primary": True,
            }
        ],
        "requirements": [
            {
                "id": "req-bracelet-001",
                "code": "REQ-SEAM-001",
                "title": "Seam straightness",
                "requirement_text": "Fabric seam must be straight within tolerance",
                "severity": "major",
                "pass_criteria": "Seam deviation less than 2mm over any 10mm span",
                "sort_order": 1,
            },
            {
                "id": "req-bracelet-002",
                "code": "REQ-CLASP-001",
                "title": "Clasp integrity",
                "requirement_text": "Clasp must open and close smoothly",
                "severity": "critical",
                "pass_criteria": "Clasp must click and hold securely",
                "sort_order": 2,
            },
        ],
        "detection_points": [
            {
                "id": "dp-bracelet-001",
                "requirement_id": "req-bracelet-001",
                "point_code": "DP-BRACELET-SEAM-001",
                "label": "Seam alignment check",
                "description": "Check seam straightness across visible surface",
                "roi_json": {"x": 0.1, "y": 0.3, "w": 0.8, "h": 0.4},
                "severity": "major",
                "sort_order": 1,
            },
            {
                "id": "dp-bracelet-002",
                "requirement_id": "req-bracelet-002",
                "point_code": "DP-BRACELET-CLASP-001",
                "label": "Clasp check",
                "description": "Check clasp for proper engagement",
                "roi_json": {"x": 0.7, "y": 0.3, "w": 0.3, "h": 0.4},
                "severity": "critical",
                "sort_order": 2,
            },
        ],
    },
]


def seed(session) -> None:
    for sku_data in SEED_DATA:
        existing = session.get(QCSkuItem, sku_data["id"])
        if existing:
            print(f"  SKU {sku_data['item_number']} already exists — skipping")
            continue

        now = _now()
        sku = QCSkuItem(
            id=sku_data["id"],
            tenant_id=TENANT,
            item_number=sku_data["item_number"],
            name=sku_data["name"],
            category=sku_data["category"],
            description=sku_data["description"],
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(sku)

        for p in sku_data["photos"]:
            photo = QCStandardPhoto(
                id=p["id"],
                tenant_id=TENANT,
                sku_id=sku_data["id"],
                image_url=p["image_url"],
                local_path=p["local_path"],
                angle=p.get("angle"),
                view_type=p.get("view_type"),
                sha256=p.get("sha256"),
                is_primary=p.get("is_primary", False),
                created_at=now,
                updated_at=now,
            )
            session.add(photo)

        for r in sku_data["requirements"]:
            req = QCInspectionRequirement(
                id=r["id"],
                tenant_id=TENANT,
                sku_id=sku_data["id"],
                code=r["code"],
                title=r["title"],
                requirement_text=r["requirement_text"],
                severity=r["severity"],
                pass_criteria=r.get("pass_criteria"),
                sort_order=r.get("sort_order", 0),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(req)

        for dp in sku_data["detection_points"]:
            point = QCDetectionPoint(
                id=dp["id"],
                tenant_id=TENANT,
                sku_id=sku_data["id"],
                requirement_id=dp.get("requirement_id"),
                point_code=dp["point_code"],
                label=dp["label"],
                description=dp.get("description"),
                roi_json=dp.get("roi_json"),
                severity=dp["severity"],
                sort_order=dp.get("sort_order", 0),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(point)

        session.commit()
        print(f"  Seeded SKU: {sku_data['item_number']} ({sku_data['id']})")


def main() -> None:
    print(f"Connecting to: {DB_URL}")
    connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
    engine = create_engine(DB_URL, connect_args=connect_args)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    with Session() as session:
        print("Seeding QC sample data...")
        seed(session)
    print("Done.")


if __name__ == "__main__":
    main()
