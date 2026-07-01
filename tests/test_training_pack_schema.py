"""Training Pack schema tests (PRD §23.4)."""
from __future__ import annotations

from tests.qcm_factories import make_detection_point, make_training_pack

from src.qc_model.schemas.training_pack import TrainingPackStatus


def test_training_pack_requires_playbook():
    pack = make_training_pack(with_playbook=False)
    assert "missing_playbook" in pack.missing_requirements()
    assert not pack.is_structurally_complete()


def test_training_pack_requires_detection_points():
    pack = make_training_pack(detection_points=[])
    assert "missing_detection_points" in pack.missing_requirements()


def test_training_pack_requires_reference_image():
    pack = make_training_pack(with_reference=False)
    assert "missing_reference_image" in pack.missing_requirements()


def test_detection_point_categories_must_be_confirmed():
    unconfirmed = make_detection_point(confirmed=False)
    pack = make_training_pack(detection_points=[unconfirmed])
    assert "unconfirmed_detection_point_categories" in pack.missing_requirements()


def test_complete_pack_is_structurally_complete():
    pack = make_training_pack()
    assert pack.missing_requirements() == []
    assert pack.is_structurally_complete()


def test_unconfirmed_pack_cannot_be_used_for_active_inspection():
    draft = make_training_pack(status=TrainingPackStatus.DRAFT)
    assert draft.is_structurally_complete()  # structure is fine
    assert not draft.is_confirmed()  # but status is not confirmed/qualified

    qualified = make_training_pack(status=TrainingPackStatus.QUALIFIED)
    assert qualified.is_confirmed()


def test_confirmed_detection_points_filters_unconfirmed():
    confirmed = make_detection_point(code="a", confirmed=True)
    unconfirmed = make_detection_point(code="b", confirmed=False)
    pack = make_training_pack(detection_points=[confirmed, unconfirmed])
    codes = [dp.code for dp in pack.confirmed_detection_points()]
    assert codes == ["a"]
