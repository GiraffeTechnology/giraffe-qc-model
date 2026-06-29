"""Tests for the seed-data-driven QC simulation dataset."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.qc_simulation.runner import (
    DATASET_ROOT,
    REQUIRED_POINT_CODES,
    final_result_from_checkpoints,
    load_jsonl,
    required_point_codes_for,
    run_simulation,
    simulate_model_payload,
    simulate_sample,
)


CHAIN_DATASET_ROOT = Path("data/qc_simulation/gold_chain_link_charm")
LABELS_PATH = DATASET_ROOT / "labels" / "expected_results.jsonl"
SYNTHETIC_METADATA_PATH = DATASET_ROOT / "synthetic" / "synthetic_metadata.jsonl"
SEED_METADATA_PATH = DATASET_ROOT / "seed" / "source_metadata.jsonl"
REAL_METADATA_PATH = DATASET_ROOT / "real" / "real_metadata.jsonl"


def _labels() -> list[dict]:
    return load_jsonl(LABELS_PATH)


def test_dataset_structure_and_seed_metadata_exist():
    assert (DATASET_ROOT / "seed" / "standard").is_dir()
    assert (DATASET_ROOT / "seed" / "pass").is_dir()
    assert (DATASET_ROOT / "synthetic" / "pass").is_dir()
    assert (DATASET_ROOT / "synthetic" / "fail_center_offcenter_subtle").is_dir()
    assert (DATASET_ROOT / "synthetic" / "fail_missing_rhinestone_subtle").is_dir()
    assert (DATASET_ROOT / "synthetic" / "fail_pearl_hairline_crack").is_dir()
    assert (DATASET_ROOT / "synthetic" / "fail_missing_pearl").is_dir()
    assert (DATASET_ROOT / "synthetic" / "fail_petal_micro_chip").is_dir()
    assert (DATASET_ROOT / "synthetic" / "mixed_defects").is_dir()
    assert (DATASET_ROOT / "real" / "standard").is_dir()
    assert (DATASET_ROOT / "real" / "fail_center_offcenter").is_dir()
    assert LABELS_PATH.exists()
    assert SYNTHETIC_METADATA_PATH.exists()
    assert REAL_METADATA_PATH.exists()
    assert SEED_METADATA_PATH.exists()

    seed_metadata = load_jsonl(SEED_METADATA_PATH)
    assert seed_metadata
    for row in seed_metadata:
        assert row["source_url"].startswith("https://")
        assert row["source_platform"]
        assert row["captured_at"]
        assert row["sku_name"] == "Artificial jewelry flower brooch / hair clip"
        assert row["image_role"] in {"standard", "pass_reference"}
        assert row["license_note"] == "public_product_page_internal_test_only"
        assert Path(row["image_path"]).exists()


def test_dataset_has_at_least_70_point_labeled_samples():
    labels = _labels()
    synthetic_metadata = load_jsonl(SYNTHETIC_METADATA_PATH)
    real_metadata = load_jsonl(REAL_METADATA_PATH)
    assert len(labels) == 72
    assert len(synthetic_metadata) == 70
    assert len(real_metadata) == 2

    metadata_by_sample = {
        row["sample_id"]: row for row in synthetic_metadata + real_metadata
    }
    sample_ids = set(metadata_by_sample)
    assert {label["sample_id"] for label in labels} == sample_ids
    for label in labels:
        assert Path(label["image_path"]).exists()
        assert label["is_synthetic"] is metadata_by_sample[label["sample_id"]]["is_synthetic"]
        checkpoint_codes = {item["code"] for item in label["expected_checkpoint_results"]}
        assert checkpoint_codes == set(REQUIRED_POINT_CODES)


def test_dataset_covers_required_synthetic_defect_categories():
    synthetic_metadata = load_jsonl(SYNTHETIC_METADATA_PATH)
    counts: dict[str, int] = {}
    for row in synthetic_metadata:
        assert row["is_synthetic"] is True
        assert row["license_note"] == "public_product_page_internal_test_only"
        counts[row["synthetic_defect_type"]] = counts.get(row["synthetic_defect_type"], 0) + 1

    assert counts == {
        "pass": 10,
        "center_alignment": 10,
        "rhinestone_count": 10,
        "pearl_surface_integrity": 10,
        "pearl_count": 10,
        "petal_integrity": 10,
        "mixed_defects": 10,
    }


def test_real_production_center_offcenter_sample_is_labeled_fail():
    labels = _labels()
    real_metadata = load_jsonl(REAL_METADATA_PATH)
    real_sample_ids = {row["sample_id"] for row in real_metadata}
    assert real_sample_ids == {
        "real_production_standard_001",
        "real_production_center_offcenter_001",
    }
    for row in real_metadata:
        assert row["is_synthetic"] is False
        assert row["license_note"] == "operator_provided_real_production_photo_internal_test_only"
        assert Path(row["image_path"]).exists()

    defect_label = next(
        label for label in labels
        if label["sample_id"] == "real_production_center_offcenter_001"
    )
    assert defect_label["is_synthetic"] is False
    assert defect_label["expected_final_result"] == "fail"
    checkpoints = {
        item["code"]: item["result"]
        for item in defect_label["expected_checkpoint_results"]
    }
    assert checkpoints["center_alignment"] == "fail"
    assert all(
        result == "pass"
        for code, result in checkpoints.items()
        if code != "center_alignment"
    )


def test_real_production_chain_missing_link_sample_is_labeled_fail():
    labels = load_jsonl(CHAIN_DATASET_ROOT / "labels" / "expected_results.jsonl")
    real_metadata = load_jsonl(CHAIN_DATASET_ROOT / "real" / "real_metadata.jsonl")
    required_codes = required_point_codes_for(CHAIN_DATASET_ROOT)

    assert required_codes == (
        "chain_link_count",
        "top_attachment_integrity",
        "bottom_charm_attachment_integrity",
        "link_alignment",
        "surface_finish_integrity",
        "incidental_abnormality",
    )
    assert len(labels) == 2
    assert len(real_metadata) == 2
    for row in real_metadata:
        assert row["is_synthetic"] is False
        assert row["license_note"] == "operator_provided_real_production_photo_internal_test_only"
        assert Path(row["image_path"]).exists()

    standard = next(
        row for row in real_metadata
        if row["sample_id"] == "real_production_chain_13_links_standard_001"
    )
    defect = next(
        row for row in real_metadata
        if row["sample_id"] == "real_production_chain_12_links_missing_one_001"
    )
    assert standard["observed_chain_link_count"] == 13
    assert defect["observed_chain_link_count"] == 12
    assert defect["expected_chain_link_count"] == 13

    defect_label = next(
        label for label in labels
        if label["sample_id"] == "real_production_chain_12_links_missing_one_001"
    )
    assert defect_label["expected_final_result"] == "fail"
    checkpoints = {
        item["code"]: item["result"]
        for item in defect_label["expected_checkpoint_results"]
    }
    assert checkpoints["chain_link_count"] == "fail"
    assert all(
        result == "pass"
        for code, result in checkpoints.items()
        if code != "chain_link_count"
    )

    outcome = simulate_sample(defect_label, required_point_codes=required_codes)
    assert outcome.actual_final_result == "fail"


def test_run_simulation_generates_required_report_schema():
    report = run_simulation(DATASET_ROOT)
    assert report["total_samples"] == 72
    assert report["synthetic_sample_count"] == 70
    assert report["real_production_sample_count"] == 2
    assert report["false_pass_count"] == 0
    assert report["false_fail_count"] == 0
    assert report["final_result_accuracy"] == 1.0
    assert report["point_level_accuracy"] == 1.0
    assert "per_defect_type_accuracy" in report
    assert "missed_defects" in report
    assert "unexpected_incidental_findings" in report
    assert "samples_failed_by_reason" in report
    assert Path(report["report_path"]).exists()


def test_run_chain_simulation_generates_required_report_schema():
    report = run_simulation(CHAIN_DATASET_ROOT)
    assert report["sku_standard"]["sku_id"] == "gold_chain_link_charm_001"
    assert report["sku_standard"]["expected_chain_link_count"] == 13
    assert report["total_samples"] == 2
    assert report["synthetic_sample_count"] == 0
    assert report["real_production_sample_count"] == 2
    assert report["false_pass_count"] == 0
    assert report["false_fail_count"] == 0
    assert report["final_result_accuracy"] == 1.0
    assert report["point_level_accuracy"] == 1.0
    assert report["per_defect_type_accuracy"]["chain_link_count"] == 1.0
    assert "real_production_chain_12_links_missing_one_001" in report["samples_failed_by_reason"][
        "one_or_more_checkpoint_failures"
    ]
    assert Path(report["report_path"]).exists()


def test_missing_checkpoint_result_cannot_pass():
    checkpoints = {code: "pass" for code in REQUIRED_POINT_CODES}
    checkpoints.pop("petal_integrity")
    result, reason = final_result_from_checkpoints(checkpoints)
    assert result == "review_required"
    assert reason and "missing_checkpoint_results" in reason


def test_unknown_point_code_is_rejected():
    label = _labels()[0]
    model_output = [{"code": code, "result": "pass"} for code in REQUIRED_POINT_CODES]
    model_output.append({"code": "unexpected_point", "result": "pass"})
    with pytest.raises(ValueError, match="Unknown point_code"):
        simulate_sample(label, model_output=model_output)


def test_empty_model_output_returns_review_required():
    label = _labels()[0]
    outcome = simulate_model_payload(label, payload={})
    assert outcome.actual_final_result == "review_required"
    assert outcome.reason == "empty_model_output"


def test_model_overall_pass_contradiction_cannot_produce_pass():
    label = next(row for row in _labels() if row["sample_id"] == "sim_center_offcenter_001")
    payload = {
        "overall_result": "pass",
        "items": [
            {"code": "center_alignment", "result": "fail"},
            {"code": "rhinestone_count", "result": "pass"},
            {"code": "pearl_count", "result": "pass"},
            {"code": "pearl_surface_integrity", "result": "pass"},
            {"code": "petal_integrity", "result": "pass"},
            {"code": "incidental_abnormality", "result": "pass"},
        ],
    }
    outcome = simulate_model_payload(label, payload)
    assert outcome.actual_final_result == "fail"


def test_critical_defect_cannot_be_converted_into_pass():
    label = next(row for row in _labels() if row["sample_id"] == "sim_missing_rhinestone_001")
    payload = {
        "overall_result": "pass",
        "items": [{"code": code, "result": "pass"} for code in REQUIRED_POINT_CODES],
    }
    outcome = simulate_model_payload(label, payload)
    assert outcome.actual_final_result == "fail"
    assert outcome.reason == "critical_defect_cannot_pass"
