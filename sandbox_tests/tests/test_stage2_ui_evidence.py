import struct
from pathlib import Path

import pytest

from sandbox_tests.stage2.ui_evidence import STATE_CONTRACTS, png_size, validate_case


def _png(path: Path, width: int = 1280, height: int = 720):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height))


def test_ui_contract_has_exactly_six_required_states():
    assert set(STATE_CONTRACTS) == {
        "simulator-ready",
        "simulated-capture",
        "cv-success",
        "cv-anomaly",
        "simulator-unavailable",
        "refresh-retry",
    }


def test_png_size_rejects_non_png(tmp_path):
    image = tmp_path / "bad.png"
    image.write_text("not png")
    with pytest.raises(ValueError, match="invalid PNG"):
        png_size(image)


def test_fail_closed_ui_requires_visible_marker(tmp_path):
    case_id = "cv-anomaly"
    _png(tmp_path / f"{case_id}.png")
    (tmp_path / f"{case_id}.xml").write_text(
        f"NON-PRODUCTION MOCK {case_id} REVIEW REQUIRED Inference calls: 0",
        encoding="utf-8",
    )
    result = validate_case(tmp_path, case_id)
    assert result["passed"] is False
    assert any("Fail closed: YES" in note for note in result["anomaly_notes"])


def test_refresh_retry_requires_ordered_before_after_event_evidence(tmp_path):
    case_id = "refresh-retry"
    _png(tmp_path / f"{case_id}.png")
    _png(tmp_path / "simulator-unavailable.png")
    (tmp_path / f"{case_id}.xml").write_text(
        "NON-PRODUCTION MOCK refresh-retry RETRY COMPLETE "
        "Inference calls: 0 Result count: 1",
        encoding="utf-8",
    )
    (tmp_path / "refresh-retry-events.log").write_text(
        "state=simulator-unavailable inference_calls=0 result_count=0 fail_closed=true\n"
        "state=refresh-retry inference_calls=0 result_count=1 fail_closed=false\n",
        encoding="utf-8",
    )
    result = validate_case(tmp_path, case_id)
    assert result["passed"] is True
    assert result["state_payload"]["before_screenshot"].endswith(
        "simulator-unavailable.png"
    )
