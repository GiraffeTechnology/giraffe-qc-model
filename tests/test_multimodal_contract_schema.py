"""
Contract schema validation tests.

Golden fixtures in tests/fixtures/contracts/ must conform to the multimodal QC contract.
These tests run in CI without any model key, real API call, or multimodal provider stack.

All three canonical result variants (pass / fail / review_required) are validated:
  - contract_version field is present and correct
  - overall_result and per-item result are one of the three canonical values
  - forbidden result values (ok, ng, unknown, needs_fix) are absent
  - confidence values are in [0.0, 1.0]
  - required fields are present in every item and in the fallback object
  - request fixture has all required fields and valid qc_points
"""

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "contracts"
CONTRACT_VERSION = "multimodal-qc-v1"
VALID_RESULTS = {"pass", "fail", "review_required"}
FORBIDDEN_RESULTS = {"ok", "ng", "unknown", "needs_fix", "good", "bad"}


def load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    assert path.exists(), f"Missing fixture: {path}"
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Contract version
# ---------------------------------------------------------------------------

class TestContractVersion:
    def test_request_has_contract_version(self):
        req = load_fixture("qc_inspection_request_v1.json")
        assert req["contract_version"] == CONTRACT_VERSION

    @pytest.mark.parametrize("fixture", [
        "qc_inspection_result_pass_v1.json",
        "qc_inspection_result_fail_v1.json",
        "qc_inspection_result_review_required_v1.json",
    ])
    def test_result_has_contract_version(self, fixture):
        result = load_fixture(fixture)
        assert result["contract_version"] == CONTRACT_VERSION


# ---------------------------------------------------------------------------
# Overall result
# ---------------------------------------------------------------------------

class TestOverallResult:
    @pytest.mark.parametrize("fixture,expected", [
        ("qc_inspection_result_pass_v1.json", "pass"),
        ("qc_inspection_result_fail_v1.json", "fail"),
        ("qc_inspection_result_review_required_v1.json", "review_required"),
    ])
    def test_overall_result_is_canonical(self, fixture, expected):
        result = load_fixture(fixture)
        assert result["overall_result"] == expected
        assert result["overall_result"] in VALID_RESULTS

    @pytest.mark.parametrize("fixture", [
        "qc_inspection_result_pass_v1.json",
        "qc_inspection_result_fail_v1.json",
        "qc_inspection_result_review_required_v1.json",
    ])
    def test_overall_result_not_forbidden(self, fixture):
        result = load_fixture(fixture)
        assert result["overall_result"] not in FORBIDDEN_RESULTS


# ---------------------------------------------------------------------------
# Per-item results
# ---------------------------------------------------------------------------

class TestItemResults:
    @pytest.mark.parametrize("fixture", [
        "qc_inspection_result_pass_v1.json",
        "qc_inspection_result_fail_v1.json",
        "qc_inspection_result_review_required_v1.json",
    ])
    def test_items_use_canonical_result_values(self, fixture):
        result = load_fixture(fixture)
        for item in result["items"]:
            assert item["result"] in VALID_RESULTS, (
                f"Item {item['qc_point_id']} has invalid result: {item['result']!r}"
            )

    @pytest.mark.parametrize("fixture", [
        "qc_inspection_result_pass_v1.json",
        "qc_inspection_result_fail_v1.json",
        "qc_inspection_result_review_required_v1.json",
    ])
    def test_items_have_required_fields(self, fixture):
        result = load_fixture(fixture)
        required = {"qc_point_id", "qc_point_code", "name", "result", "confidence", "reason"}
        for item in result["items"]:
            missing = required - item.keys()
            assert not missing, (
                f"Item {item.get('qc_point_id', '?')} missing fields: {missing}"
            )

    @pytest.mark.parametrize("fixture", [
        "qc_inspection_result_pass_v1.json",
        "qc_inspection_result_fail_v1.json",
        "qc_inspection_result_review_required_v1.json",
    ])
    def test_item_confidence_in_range(self, fixture):
        result = load_fixture(fixture)
        for item in result["items"]:
            assert 0.0 <= item["confidence"] <= 1.0, (
                f"Item {item['qc_point_id']} confidence out of range: {item['confidence']}"
            )

    @pytest.mark.parametrize("fixture", [
        "qc_inspection_result_pass_v1.json",
        "qc_inspection_result_fail_v1.json",
        "qc_inspection_result_review_required_v1.json",
    ])
    def test_items_not_forbidden_values(self, fixture):
        result = load_fixture(fixture)
        for item in result["items"]:
            assert item["result"] not in FORBIDDEN_RESULTS, (
                f"Item {item['qc_point_id']} has forbidden result: {item['result']!r}"
            )


# ---------------------------------------------------------------------------
# Overall confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    @pytest.mark.parametrize("fixture", [
        "qc_inspection_result_pass_v1.json",
        "qc_inspection_result_fail_v1.json",
        "qc_inspection_result_review_required_v1.json",
    ])
    def test_overall_confidence_in_range(self, fixture):
        result = load_fixture(fixture)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_review_required_has_zero_confidence(self):
        result = load_fixture("qc_inspection_result_review_required_v1.json")
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

class TestFallback:
    @pytest.mark.parametrize("fixture", [
        "qc_inspection_result_pass_v1.json",
        "qc_inspection_result_fail_v1.json",
        "qc_inspection_result_review_required_v1.json",
    ])
    def test_fallback_has_used_bool(self, fixture):
        result = load_fixture(fixture)
        assert "fallback" in result
        assert isinstance(result["fallback"]["used"], bool)

    def test_pass_fallback_not_used(self):
        assert load_fixture("qc_inspection_result_pass_v1.json")["fallback"]["used"] is False

    def test_fail_fallback_not_used(self):
        assert load_fixture("qc_inspection_result_fail_v1.json")["fallback"]["used"] is False

    def test_review_required_fallback_not_used(self):
        # review_required from missing model — backend proxy was not invoked either
        assert load_fixture("qc_inspection_result_review_required_v1.json")["fallback"]["used"] is False


# ---------------------------------------------------------------------------
# Forbidden values (PRD §3.2)
# ---------------------------------------------------------------------------

class TestNoForbiddenValues:
    """Confirm canonical result names only. Never ok/ng/unknown/needs_fix."""

    def _assert_no_forbidden(self, obj: dict) -> None:
        overall = obj.get("overall_result", "")
        assert overall not in FORBIDDEN_RESULTS, f"Forbidden overall_result: {overall!r}"
        for item in obj.get("items", []):
            item_result = item.get("result", "")
            assert item_result not in FORBIDDEN_RESULTS, (
                f"Forbidden item result for {item.get('qc_point_id', '?')}: {item_result!r}"
            )

    def test_pass_fixture_canonical(self):
        self._assert_no_forbidden(load_fixture("qc_inspection_result_pass_v1.json"))

    def test_fail_fixture_canonical(self):
        self._assert_no_forbidden(load_fixture("qc_inspection_result_fail_v1.json"))

    def test_review_required_fixture_canonical(self):
        self._assert_no_forbidden(load_fixture("qc_inspection_result_review_required_v1.json"))


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class TestRequestSchema:
    def test_request_has_required_fields(self):
        req = load_fixture("qc_inspection_request_v1.json")
        required = {
            "contract_version", "tenant_id", "sku_id", "standard_id",
            "inspection_id", "standard_image_paths", "captured_image_path", "qc_points",
        }
        missing = required - req.keys()
        assert not missing, f"Request missing fields: {missing}"

    def test_standard_image_paths_is_list(self):
        req = load_fixture("qc_inspection_request_v1.json")
        assert isinstance(req["standard_image_paths"], list)
        assert len(req["standard_image_paths"]) >= 1

    def test_qc_points_have_required_fields(self):
        req = load_fixture("qc_inspection_request_v1.json")
        required = {"qc_point_id", "qc_point_code", "name", "description"}
        for point in req["qc_points"]:
            missing = required - point.keys()
            assert not missing, f"QC point missing fields: {missing}"


# ---------------------------------------------------------------------------
# Contract constant import (standalone module check)
# ---------------------------------------------------------------------------

class TestContractModule:
    def test_contract_module_importable(self):
        """src/multimodal/contract.py must be importable standalone."""
        import importlib
        import sys
        # Add src to path if not already present for bare-main CI environments.
        import os
        src_path = str(Path(__file__).parent.parent / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        mod = importlib.import_module("multimodal.contract")
        assert mod.QC_CONTRACT_VERSION == CONTRACT_VERSION
        assert "pass" in mod.VALID_RESULTS
        assert "fail" in mod.VALID_RESULTS
        assert "review_required" in mod.VALID_RESULTS
        assert mod.normalize_result("pass") == "pass"
        assert mod.normalize_result("ok") == "review_required"
        assert mod.normalize_result(None) == "review_required"
