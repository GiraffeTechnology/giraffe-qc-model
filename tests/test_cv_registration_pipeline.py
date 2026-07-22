"""Tests for the pad_router integration of standard-photo registration
(STAGE2_OPEN_SOURCE_CV_EVALUATION_20260722): a detection point with an
authored region must have its CV analysis run against a correctly-located,
registered crop of the captured image, and must fail closed --
never fall back to the unlocated full frame -- when registration cannot be
established."""
from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.pad_router import _RegistrationFailed, _registered_crop
from src.db.models import Base
import src.db.sku_models  # noqa: F401 — registers tables
from src.db.sku_models import QCSkuItem, QCStandardPhoto

FIXTURE = Path(__file__).parent / "fixtures" / "qc" / "flower_brooch_4petal_3pearl_7rhinestone.jpg"


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield session
    session.close()
    engine.dispose()


def _make_standard_photo(db_session, tmp_path, *, image_bytes: bytes) -> QCStandardPhoto:
    now = datetime.now(timezone.utc)
    sku = QCSkuItem(
        id=uuid.uuid4().hex, tenant_id="default", item_number="REG-001",
        name="Registration test SKU", status="active", created_at=now, updated_at=now,
    )
    db_session.add(sku)
    photo_path = tmp_path / "standard.jpg"
    photo_path.write_bytes(image_bytes)
    photo = QCStandardPhoto(
        id=uuid.uuid4().hex, tenant_id="default", sku_id=sku.id,
        local_path=str(photo_path), is_primary=True,
        created_at=now, updated_at=now,
    )
    db_session.add(photo)
    db_session.commit()
    return photo


def _synthetic_capture(image, *, angle_deg=6.0, scale=0.92, tx=25, ty=-15):
    h, w = image.shape[:2]
    center = (w / 2, h / 2)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, scale)
    homography = np.vstack([matrix, [0, 0, 1]]).astype(np.float64)
    homography[0, 2] += tx
    homography[1, 2] += ty
    return cv2.warpPerspective(image, homography, (w, h), borderValue=(30, 60, 30))


def test_registered_crop_locates_region_on_a_realistic_recapture(db_session, tmp_path):
    standard_image = cv2.imread(str(FIXTURE))
    assert standard_image is not None
    ok, encoded = cv2.imencode(".jpg", standard_image)
    assert ok
    photo = _make_standard_photo(db_session, tmp_path, image_bytes=encoded.tobytes())
    captured_image = _synthetic_capture(standard_image)

    point = types.SimpleNamespace(
        regions_json=[{"image_id": photo.id, "x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4}],
    )
    crop = _registered_crop(db_session, "default", point, captured_image, {})
    assert crop is not None
    assert crop.shape[0] > 0 and crop.shape[1] > 0
    # The crop should be a meaningfully smaller region than the full frame,
    # proving it actually used the mapped ROI rather than returning the
    # whole captured image.
    assert crop.shape[0] < captured_image.shape[0]
    assert crop.shape[1] < captured_image.shape[1]


def test_registered_crop_fails_closed_on_unrelated_captured_image(db_session, tmp_path):
    standard_image = cv2.imread(str(FIXTURE))
    ok, encoded = cv2.imencode(".jpg", standard_image)
    assert ok
    photo = _make_standard_photo(db_session, tmp_path, image_bytes=encoded.tobytes())
    unrelated = np.random.default_rng(3).integers(0, 255, size=standard_image.shape, dtype=np.uint8).astype(np.uint8)

    point = types.SimpleNamespace(
        regions_json=[{"image_id": photo.id, "x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4}],
    )
    with pytest.raises(_RegistrationFailed, match="registration_failed"):
        _registered_crop(db_session, "default", point, unrelated, {})


def test_registered_crop_fails_closed_without_image_id(db_session):
    point = types.SimpleNamespace(regions_json=[{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}])
    dummy = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(_RegistrationFailed, match="region_missing_image_id"):
        _registered_crop(db_session, "default", point, dummy, {})


def test_registered_crop_fails_closed_when_standard_photo_missing(db_session):
    point = types.SimpleNamespace(
        regions_json=[{"image_id": "does-not-exist", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
    )
    dummy = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(_RegistrationFailed, match="registration_failed"):
        _registered_crop(db_session, "default", point, dummy, {})


def test_registration_cache_is_reused_across_points(db_session, tmp_path):
    """Two points that reference the same standard photo must only pay for
    registration once."""
    standard_image = cv2.imread(str(FIXTURE))
    ok, encoded = cv2.imencode(".jpg", standard_image)
    assert ok
    photo = _make_standard_photo(db_session, tmp_path, image_bytes=encoded.tobytes())
    captured_image = _synthetic_capture(standard_image)

    cache: dict = {}
    point_a = types.SimpleNamespace(
        regions_json=[{"image_id": photo.id, "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3}],
    )
    point_b = types.SimpleNamespace(
        regions_json=[{"image_id": photo.id, "x": 0.5, "y": 0.5, "w": 0.3, "h": 0.3}],
    )
    _registered_crop(db_session, "default", point_a, captured_image, cache)
    assert photo.id in cache
    cached_entry = cache[photo.id]
    _registered_crop(db_session, "default", point_b, captured_image, cache)
    assert cache[photo.id] is cached_entry
