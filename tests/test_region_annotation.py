"""Tests for detection-point region annotation (PRD Authoring Extension §2).

- A detection point supports zero, one, or multiple bounding-box regions.
- Regions reference a standard photo of the same SKU; coords are normalized 0–1.
- Malformed regions / foreign photos are rejected fail-closed.
- Regions surface in the studio detection-point view and the bundle manifest.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401 — register tables
import src.db.studio_models  # noqa: F401 — register tables

from src.db.sku_models import (
    QCDetectionPoint,
    QCSkuItem,
    QCSkuStandardRevision,
    QCStandardPhoto,
)
from src.qc_model.studio.regions import (
    InvalidRegion,
    normalize_regions,
    set_detection_point_regions,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _setup(db, tenant_id="t1"):
    sku = QCSkuItem(id=uuid.uuid4().hex, tenant_id=tenant_id, item_number="SKU-1", name="Item")
    db.add(sku)
    db.commit()
    rev = QCSkuStandardRevision(
        id=uuid.uuid4().hex, sku_id=sku.id, tenant_id=tenant_id, revision_no=1, status="active"
    )
    db.add(rev)
    photo = QCStandardPhoto(id=uuid.uuid4().hex, tenant_id=tenant_id, sku_id=sku.id, view_type="front")
    db.add(photo)
    dp = QCDetectionPoint(
        id=uuid.uuid4().hex, tenant_id=tenant_id, sku_id=sku.id,
        standard_revision_id=rev.id, point_code="PEARL_COUNT", label="Pearl Count",
    )
    db.add(dp)
    db.commit()
    return sku, rev, photo, dp


# ── normalize_regions ─────────────────────────────────────────────────────────


def test_zero_regions_is_valid():
    assert normalize_regions([], {"img1"}) == []
    assert normalize_regions(None, {"img1"}) == []


def test_multiple_regions_accepted():
    regions = [
        {"image_id": "img1", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
        {"image_id": "img1", "x": 0.5, "y": 0.5, "w": 0.3, "h": 0.3},
    ]
    clean = normalize_regions(regions, {"img1"})
    assert len(clean) == 2
    assert clean[0]["x"] == 0.1


def test_region_ints_coerced_to_float():
    clean = normalize_regions([{"image_id": "img1", "x": 0, "y": 0, "w": 1, "h": 1}], {"img1"})
    assert clean[0] == {"image_id": "img1", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}


def test_region_out_of_bounds_rejected():
    with pytest.raises(InvalidRegion):
        normalize_regions([{"image_id": "img1", "x": 0.9, "y": 0.1, "w": 0.2, "h": 0.2}], {"img1"})


def test_region_out_of_range_coord_rejected():
    with pytest.raises(InvalidRegion):
        normalize_regions([{"image_id": "img1", "x": -0.1, "y": 0.1, "w": 0.2, "h": 0.2}], {"img1"})


def test_region_zero_area_rejected():
    with pytest.raises(InvalidRegion):
        normalize_regions([{"image_id": "img1", "x": 0.1, "y": 0.1, "w": 0.0, "h": 0.2}], {"img1"})


def test_region_unknown_image_rejected():
    with pytest.raises(InvalidRegion):
        normalize_regions([{"image_id": "nope", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}], {"img1"})


def test_region_extra_keys_rejected():
    with pytest.raises(InvalidRegion):
        normalize_regions(
            [{"image_id": "img1", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "shape": "polygon"}],
            {"img1"},
        )


def test_region_bool_coord_rejected():
    with pytest.raises(InvalidRegion):
        normalize_regions([{"image_id": "img1", "x": True, "y": 0.1, "w": 0.2, "h": 0.2}], {"img1"})


# ── set_detection_point_regions ───────────────────────────────────────────────


def test_set_regions_persists(db):
    sku, rev, photo, dp = _setup(db)
    updated = set_detection_point_regions(
        db, dp.id,
        [{"image_id": photo.id, "x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1}],
        tenant_id="t1",
    )
    assert len(updated.regions_json) == 1
    assert updated.regions_json[0]["image_id"] == photo.id


def test_set_regions_clears_with_empty_list(db):
    sku, rev, photo, dp = _setup(db)
    set_detection_point_regions(
        db, dp.id, [{"image_id": photo.id, "x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1}], tenant_id="t1"
    )
    cleared = set_detection_point_regions(db, dp.id, [], tenant_id="t1")
    assert cleared.regions_json == []


def test_set_regions_rejects_photo_from_other_sku(db):
    sku, rev, photo, dp = _setup(db)
    other = QCStandardPhoto(id=uuid.uuid4().hex, tenant_id="t1", sku_id="OTHER-SKU")
    db.add(other)
    db.commit()
    with pytest.raises(InvalidRegion):
        set_detection_point_regions(
            db, dp.id, [{"image_id": other.id, "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}], tenant_id="t1"
        )


def test_studio_dp_view_includes_regions(db):
    from src.qc_model.studio.service import _dp_view
    sku, rev, photo, dp = _setup(db)
    set_detection_point_regions(
        db, dp.id, [{"image_id": photo.id, "x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1}], tenant_id="t1"
    )
    db.refresh(dp)
    view = _dp_view(dp)
    assert view["regions"] == dp.regions_json
    assert view["regions"][0]["image_id"] == photo.id
