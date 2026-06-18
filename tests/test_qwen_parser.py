"""Tests for the QWEN output parser."""
from __future__ import annotations

import json
import pytest

from src.qwen.parser import parse_qwen_output
from src.qwen.schema import QwenInspectionOutput


EXPECTED_IDS = ["qp_001", "qp_002", "qp_003"]


def _make_valid_json(
    overall_result="pass",
    confidence=0.95,
    items=None,
    model_name="qwen-vl-max",
) -> str:
    if items is None:
        items = [
            {
                "qc_point_id": "qp_001",
                "qc_point_code": "COLOR_CHECK",
                "name": "Color Check",
                "result": "pass",
                "confidence": 0.98,
                "reason": "Color matches standard",
                "evidence": {},
            },
            {
                "qc_point_id": "qp_002",
                "qc_point_code": "LABEL_CHECK",
                "name": "Label Check",
                "result": "pass",
                "confidence": 0.92,
                "reason": "Label is correctly placed",
                "evidence": {},
            },
            {
                "qc_point_id": "qp_003",
                "qc_point_code": "STITCH_CHECK",
                "name": "Stitch Check",
                "result": "pass",
                "confidence": 0.87,
                "reason": "Stitching is uniform",
                "evidence": {},
            },
        ]
    return json.dumps({
        "overall_result": overall_result,
        "confidence": confidence,
        "model_name": model_name,
        "summary": "All checks passed",
        "items": items,
    })


class TestValidJsonParsing:
    def test_valid_json_parses_correctly(self):
        raw = _make_valid_json()
        result = parse_qwen_output(raw, EXPECTED_IDS, "cloud_qwen")
        assert isinstance(result, QwenInspectionOutput)
        assert result.overall_result == "pass"
        assert result.confidence == 0.95
        assert len(result.items) == 3

    def test_all_items_have_correct_fields(self):
        raw = _make_valid_json()
        result = parse_qwen_output(raw, EXPECTED_IDS, "cloud_qwen")
        for item in result.items:
            assert item.qc_point_id in EXPECTED_IDS
            assert item.result in ("pass", "fail", "review_required")
            assert 0.0 <= item.confidence <= 1.0
            assert isinstance(item.reason, str)

    def test_engine_preserved(self):
        raw = _make_valid_json()
        result = parse_qwen_output(raw, EXPECTED_IDS, "my_engine")
        assert result.engine == "my_engine"


class TestMarkdownWrappedJson:
    def test_markdown_code_block_parsed(self):
        json_content = _make_valid_json()
        raw = f"```json\n{json_content}\n```"
        result = parse_qwen_output(raw, EXPECTED_IDS, "cloud_qwen")
        assert result.overall_result == "pass"
        assert len(result.items) == 3

    def test_markdown_code_block_without_language(self):
        json_content = _make_valid_json()
        raw = f"```\n{json_content}\n```"
        result = parse_qwen_output(raw, EXPECTED_IDS, "cloud_qwen")
        assert result.overall_result == "pass"

    def test_markdown_with_extra_text_around(self):
        json_content = _make_valid_json()
        raw = f"Here is my analysis:\n```json\n{json_content}\n```\nLet me know if you need more details."
        result = parse_qwen_output(raw, EXPECTED_IDS, "cloud_qwen")
        assert result.overall_result == "pass"


class TestMissingQcPoints:
    def test_missing_qc_point_becomes_review_required(self):
        # Only provide qp_001, qp_002 but not qp_003
        items = [
            {
                "qc_point_id": "qp_001",
                "qc_point_code": "COLOR_CHECK",
                "name": "Color Check",
                "result": "pass",
                "confidence": 0.9,
                "reason": "OK",
            },
            {
                "qc_point_id": "qp_002",
                "qc_point_code": "LABEL_CHECK",
                "name": "Label Check",
                "result": "pass",
                "confidence": 0.9,
                "reason": "OK",
            },
        ]
        raw = _make_valid_json(items=items)
        result = parse_qwen_output(raw, EXPECTED_IDS, "cloud_qwen")

        # qp_003 should be filled as review_required
        qp_003_items = [i for i in result.items if i.qc_point_id == "qp_003"]
        assert len(qp_003_items) == 1
        assert qp_003_items[0].result == "review_required"
        assert qp_003_items[0].confidence == 0.0

    def test_all_items_present_when_some_missing(self):
        items = []
        raw = _make_valid_json(items=items)
        result = parse_qwen_output(raw, EXPECTED_IDS, "cloud_qwen")
        assert len(result.items) == len(EXPECTED_IDS)
        for item in result.items:
            assert item.result == "review_required"


class TestHallucinatedQcPoints:
    def test_hallucinated_id_rejected_from_items(self):
        items = [
            {
                "qc_point_id": "qp_001",
                "qc_point_code": "COLOR_CHECK",
                "name": "Color Check",
                "result": "pass",
                "confidence": 0.9,
                "reason": "OK",
            },
            {
                "qc_point_id": "qp_HALLUCINATED_999",
                "qc_point_code": "FAKE",
                "name": "Fake Check",
                "result": "fail",
                "confidence": 0.9,
                "reason": "This ID does not exist",
            },
        ]
        raw = json.dumps({
            "overall_result": "pass",
            "confidence": 0.9,
            "model_name": "test",
            "items": items,
        })
        result = parse_qwen_output(raw, ["qp_001"], "cloud_qwen")
        # Hallucinated ID should not be in results
        item_ids = {i.qc_point_id for i in result.items}
        assert "qp_HALLUCINATED_999" not in item_ids

    def test_valid_id_kept_hallucinated_removed(self):
        items = [
            {
                "qc_point_id": "qp_001",
                "qc_point_code": "COLOR_CHECK",
                "name": "Color Check",
                "result": "pass",
                "confidence": 0.9,
                "reason": "OK",
            },
            {
                "qc_point_id": "FAKE_ID",
                "qc_point_code": "FAKE",
                "name": "Fake",
                "result": "pass",
                "confidence": 0.9,
                "reason": "fake",
            },
        ]
        raw = json.dumps({
            "overall_result": "pass",
            "confidence": 0.9,
            "model_name": "test",
            "items": items,
        })
        result = parse_qwen_output(raw, ["qp_001"], "cloud_qwen")
        item_ids = {i.qc_point_id for i in result.items}
        assert "qp_001" in item_ids
        assert "FAKE_ID" not in item_ids


class TestInvalidJsonFailClosed:
    def test_invalid_json_returns_review_required(self):
        result = parse_qwen_output("not json at all", EXPECTED_IDS, "cloud_qwen")
        assert result.overall_result == "review_required"

    def test_empty_string_returns_review_required(self):
        result = parse_qwen_output("", EXPECTED_IDS, "cloud_qwen")
        assert result.overall_result == "review_required"

    def test_whitespace_only_returns_review_required(self):
        result = parse_qwen_output("   \n\t  ", EXPECTED_IDS, "cloud_qwen")
        assert result.overall_result == "review_required"

    def test_invalid_overall_result_returns_review_required(self):
        raw = json.dumps({
            "overall_result": "INVALID_VALUE",
            "confidence": 0.9,
            "model_name": "test",
            "items": [],
        })
        result = parse_qwen_output(raw, EXPECTED_IDS, "cloud_qwen")
        assert result.overall_result == "review_required"

    def test_fail_closed_has_fallback_set(self):
        result = parse_qwen_output("garbage", EXPECTED_IDS, "test_engine")
        assert result.fallback.used is True
        assert result.fallback.reason is not None

    def test_fail_closed_engine_preserved(self):
        result = parse_qwen_output("garbage", EXPECTED_IDS, "my_engine")
        assert result.engine == "my_engine"


class TestConfidenceClamping:
    def test_confidence_above_1_clamped_to_1(self):
        raw = json.dumps({
            "overall_result": "pass",
            "confidence": 1.5,
            "model_name": "test",
            "items": [],
        })
        result = parse_qwen_output(raw, [], "cloud_qwen")
        assert result.confidence == 1.0

    def test_confidence_below_0_clamped_to_0(self):
        raw = json.dumps({
            "overall_result": "pass",
            "confidence": -0.3,
            "model_name": "test",
            "items": [],
        })
        result = parse_qwen_output(raw, [], "cloud_qwen")
        assert result.confidence == 0.0

    def test_item_confidence_clamped(self):
        items = [
            {
                "qc_point_id": "qp_001",
                "qc_point_code": "TEST",
                "name": "Test",
                "result": "pass",
                "confidence": 2.5,  # out of range
                "reason": "OK",
            }
        ]
        raw = _make_valid_json(items=items)
        result = parse_qwen_output(raw, ["qp_001"], "cloud_qwen")
        qp_001 = next(i for i in result.items if i.qc_point_id == "qp_001")
        assert qp_001.confidence == 1.0

    def test_item_confidence_negative_clamped(self):
        items = [
            {
                "qc_point_id": "qp_001",
                "qc_point_code": "TEST",
                "name": "Test",
                "result": "pass",
                "confidence": -1.0,
                "reason": "OK",
            }
        ]
        raw = _make_valid_json(items=items)
        result = parse_qwen_output(raw, ["qp_001"], "cloud_qwen")
        qp_001 = next(i for i in result.items if i.qc_point_id == "qp_001")
        assert qp_001.confidence == 0.0
