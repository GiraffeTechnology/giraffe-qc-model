from __future__ import annotations

import pytest

from sandbox_tests.stage2.gate import Stage2DecisionRequired, Stage2Gate
from sandbox_tests.stage2.runner import build_blocked_report, main


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
