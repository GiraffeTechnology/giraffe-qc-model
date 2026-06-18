"""Tests for the QWEN QC prompt builder."""
from __future__ import annotations

import pytest

from src.qwen.prompt_builder import build_prompt, PROMPT_VERSION
from src.qwen.schema import (
    CapturePhotoInput,
    QcPointInput,
    StandardPhotoInput,
)


SCHEMA_JSON = '{"overall_result": "pass|fail|review_required", "items": []}'


@pytest.fixture
def std_photos():
    return [
        StandardPhotoInput(photo_id="STD-01", local_path="/tmp/std_front.jpg", angle="front"),
        StandardPhotoInput(photo_id="STD-02", local_path="/tmp/std_back.jpg",  angle="back"),
    ]


@pytest.fixture
def cap_photo():
    return CapturePhotoInput(photo_id="CAP-01", local_path="/tmp/cap.jpg")


@pytest.fixture
def qc_points():
    return [
        QcPointInput(qc_point_id="QC-01", qc_point_code="color",  name="Color",  description="Surface color must match standard"),
        QcPointInput(qc_point_id="QC-02", qc_point_code="border", name="Border", description="Border must be intact"),
        QcPointInput(qc_point_id="QC-03", qc_point_code="defect", name="Defect", description="No surface defects"),
    ]


class TestVersionEmbedding:
    def test_prompt_version_constant_is_correct(self):
        assert PROMPT_VERSION == "qwen-qc-v1"

    def test_prompt_contains_version_string(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        assert "qwen-qc-v1" in p

    def test_prompt_version_not_only_in_comments(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        # Must be in the prompt text itself, not just the Python module
        lines_with_version = [l for l in p.splitlines() if "qwen-qc-v1" in l]
        assert len(lines_with_version) >= 1


class TestQcPointsIncluded:
    def test_all_qc_point_ids_present(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        for point in qc_points:
            assert point.qc_point_id in p

    def test_all_qc_point_codes_present(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        for point in qc_points:
            assert point.qc_point_code in p

    def test_all_qc_point_names_present(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        for point in qc_points:
            assert point.name in p

    def test_all_qc_point_descriptions_present(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        for point in qc_points:
            assert point.description in p

    def test_no_qc_points_produces_valid_prompt(self, std_photos, cap_photo):
        p = build_prompt(std_photos, cap_photo, [], SCHEMA_JSON)
        assert p.strip() != ""
        assert "qwen-qc-v1" in p

    def test_roi_json_included_when_present(self, std_photos, cap_photo):
        points = [QcPointInput(
            qc_point_id="QC-ROI",
            qc_point_code="roi_test",
            name="ROI Test",
            description="Test ROI inclusion",
            roi_json={"x": 10, "y": 20, "w": 50, "h": 50},
        )]
        p = build_prompt(std_photos, cap_photo, points, SCHEMA_JSON)
        assert "roi" in p.lower() or "10" in p

    def test_rule_type_included_when_present(self, std_photos, cap_photo):
        points = [QcPointInput(
            qc_point_id="QC-RULE",
            qc_point_code="rule_test",
            name="Rule Test",
            description="Test rule_type inclusion",
            rule_type="exact_match",
        )]
        p = build_prompt(std_photos, cap_photo, points, SCHEMA_JSON)
        assert "exact_match" in p


class TestPhotosIncluded:
    def test_standard_photo_paths_in_prompt(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        for photo in std_photos:
            assert photo.local_path in p

    def test_standard_photo_ids_in_prompt(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        for photo in std_photos:
            assert photo.photo_id in p

    def test_capture_photo_path_in_prompt(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        assert cap_photo.local_path in p

    def test_capture_photo_id_in_prompt(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        assert cap_photo.photo_id in p

    def test_angle_included_when_present(self, cap_photo, qc_points):
        photos = [StandardPhotoInput(photo_id="S1", local_path="/tmp/s.jpg", angle="left_side")]
        p = build_prompt(photos, cap_photo, qc_points, SCHEMA_JSON)
        assert "left_side" in p

    def test_no_standard_photos_handled_gracefully(self, cap_photo, qc_points):
        p = build_prompt([], cap_photo, qc_points, SCHEMA_JSON)
        assert p.strip() != ""
        assert "qwen-qc-v1" in p


class TestSchemaEmbedding:
    def test_schema_json_embedded_in_prompt(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        assert SCHEMA_JSON in p

    def test_prompt_tells_model_json_only_output(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        assert "JSON" in p or "json" in p.lower()


class TestHallucinationGuard:
    def test_prompt_instructs_not_to_hallucinate_ids(self, std_photos, cap_photo, qc_points):
        p = build_prompt(std_photos, cap_photo, qc_points, SCHEMA_JSON)
        # Prompt must tell the model to only use listed IDs
        lowered = p.lower()
        assert "only" in lowered or "listed" in lowered or "do not" in lowered

    def test_single_qc_point_prompt_still_valid(self, std_photos, cap_photo):
        points = [QcPointInput(
            qc_point_id="QC-ONLY",
            qc_point_code="only",
            name="Only Point",
            description="Single point test",
        )]
        p = build_prompt(std_photos, cap_photo, points, SCHEMA_JSON)
        assert "QC-ONLY" in p
        assert "qwen-qc-v1" in p
