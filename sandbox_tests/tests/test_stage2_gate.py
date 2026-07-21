from __future__ import annotations

from pathlib import Path

import pytest

from sandbox_tests.stage2.gate import Stage2DecisionRequired, Stage2Gate
from sandbox_tests.stage2.runner import (
    REQUIRED_UI_CASES,
    build_blocked_report,
    build_completed_report,
    main,
)


def test_stage2_gate_has_no_default_simulation_method(monkeypatch):
    monkeypatch.delenv("STAGE2_SIMULATION_METHOD", raising=False)
    monkeypatch.delenv("STAGE2_EXTERNAL_DRIVE_ROOT", raising=False)
    with pytest.raises(Stage2DecisionRequired, match="Q1 decision required"):
        Stage2Gate.from_environment()


def test_stage2_gate_rejects_unselected_external_volume(monkeypatch):
    monkeypatch.setenv("STAGE2_SIMULATION_METHOD", "qemu_aarch64")
    monkeypatch.delenv("STAGE2_EXTERNAL_DRIVE_ROOT", raising=False)
    with pytest.raises(Stage2DecisionRequired, match="external-volume decision"):
        Stage2Gate.from_environment()


def test_stage2_gate_rejects_non_external_root(monkeypatch):
    monkeypatch.setenv("STAGE2_SIMULATION_METHOD", "filesystem_level")
    monkeypatch.setenv("STAGE2_EXTERNAL_DRIVE_ROOT", "/tmp/stage2")
    with pytest.raises(Stage2DecisionRequired, match="below /Volumes"):
        Stage2Gate.from_environment()


@pytest.mark.parametrize(
    "method",
    ["qemu_aarch64", "native_container", "filesystem_level"],
)
def test_stage2_gate_accepts_only_recorded_methods_with_ui_required(monkeypatch, method):
    monkeypatch.setenv("STAGE2_SIMULATION_METHOD", method)
    monkeypatch.setenv("STAGE2_EXTERNAL_DRIVE_ROOT", "/Volumes/selected/stage2")
    gate = Stage2Gate.from_environment()
    assert gate.method == method
    assert gate.ui_validation_required is True


def test_stage2_runner_writes_blocked_report_until_q1_is_selected(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("STAGE2_SIMULATION_METHOD", raising=False)
    monkeypatch.delenv("STAGE2_EXTERNAL_DRIVE_ROOT", raising=False)
    report = tmp_path / "stage2_report.json"
    assert main(["--report", str(report)]) == 2
    value = build_blocked_report("Q1 decision required")
    assert value["status"] == "blocked"
    assert value["summary"]["ui_validation_required"] is True
    assert not any(value["acceptance"].values())
    assert report.is_file()
    assert report.with_suffix(".md").is_file()


def _probe(machine: str):
    return {
        "runtime": {"machine": machine, "python": "3.12", "opencv": "4.6"},
        "model_invoked": False,
        "camera_connected": False,
        "cases": [
            {
                "case_id": "visual_defect-positive-01",
                "category": "visual_defect",
                "input_ref": "tests/fixtures/qc/capture_red_square_pass.png",
                "input_sha256": "abc",
                "cv_result": {
                    "brightness_mean": 60.0,
                    "preanalysis": {"analyzers": [{"count": 1}]},
                },
            }
        ],
    }


def test_completed_report_requires_real_arm64_marker_and_all_ui_cases():
    ui = {
        "platform": "android_emulator",
        "build_variant": "padLocalDebug",
        "cases": [
            {
                "case_id": case_id,
                "screenshot": f"evidence/{case_id}.png",
                "state_payload": {"mock_label_visible": True},
                "passed": True,
            }
            for case_id in sorted(REQUIRED_UI_CASES)
        ],
    }
    report = build_completed_report(
        gate=Stage2Gate("qemu_aarch64", Path("/Volumes/N1_WORK/giraffe-stage2")),
        baseline=_probe("x86_64"),
        arm64=_probe("aarch64"),
        drive={
            "volume_name": "N1_WORK",
            "write_fsync_completed": True,
            "read_back_completed": True,
            "sha256_matches": True,
        },
        ui=ui,
        difference_list_complete=True,
        limitations_recorded=True,
    )
    assert report["status"] == "passed"
    assert report["summary"]["model_call_count"] == 0
    assert report["acceptance"]["ui_validation_complete"] is True


def test_completed_report_rejects_x86_guest_even_when_outputs_match():
    report = build_completed_report(
        gate=Stage2Gate("qemu_aarch64", Path("/Volumes/N1_WORK/giraffe-stage2")),
        baseline=_probe("x86_64"),
        arm64=_probe("x86_64"),
        drive={
            "volume_name": "N1_WORK",
            "write_fsync_completed": True,
            "read_back_completed": True,
            "sha256_matches": True,
        },
        ui={"cases": []},
        difference_list_complete=True,
        limitations_recorded=True,
    )
    assert report["status"] == "failed"
    assert not report["acceptance"]["cv_module_complete_without_arch_or_dependency_error"]
