from pathlib import Path

from sandbox_tests.stage2.chrome_ui_evidence import build_manifest
from sandbox_tests.stage2.chrome_ui_server import STATE_CONTRACTS, build_state


def test_chrome_ui_exposes_all_required_states() -> None:
    assert set(STATE_CONTRACTS) == {
        "simulator-ready",
        "simulated-capture",
        "cv-success",
        "cv-anomaly",
        "simulator-unavailable",
        "refresh-retry",
    }


def test_chrome_ui_uses_recorded_arm64_and_drive_evidence() -> None:
    state = build_state("simulator-ready")
    assert state["method"] == "QEMU aarch64"
    assert state["machine"] == "aarch64"
    assert state["external_drive_ready"] is True
    assert state["camera_connected"] is False
    assert state["inference_call_count"] == 0


def test_chrome_ui_fails_closed_for_anomaly_and_unavailable() -> None:
    anomaly = build_state("cv-anomaly")
    unavailable = build_state("simulator-unavailable")
    assert anomaly["status"] == "REVIEW REQUIRED"
    assert anomaly["fail_closed"] is True
    assert unavailable["status"] == "BLOCKED"
    assert unavailable["fail_closed"] is True


def test_chrome_ui_states_have_english_and_chinese_copy() -> None:
    for case_id in STATE_CONTRACTS:
        translations = build_state(case_id)["translations"]
        assert set(translations) == {"en", "zh-CN"}
        for language in ("en", "zh-CN"):
            assert all(translations[language][key] for key in ("heading", "status", "detail"))


def test_chrome_ui_manifest_accepts_captured_evidence() -> None:
    root = Path("sandbox_tests/reports/evidence/stage2/ui")
    manifest = build_manifest(root, "test-sha")
    assert manifest["platform"] == "chrome"
    assert len(manifest["cases"]) == 6
    assert all(case["passed"] for case in manifest["cases"])
