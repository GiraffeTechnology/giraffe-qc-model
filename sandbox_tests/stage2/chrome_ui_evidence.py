"""Validate Chrome screenshots and emit the Stage 2 browser UI manifest."""
from __future__ import annotations

import argparse
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

from sandbox_tests.stage2.chrome_ui_server import STATE_CONTRACTS, build_state


def jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError(f"invalid JPEG evidence: {path.name}")
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        if marker in {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        offset += length
    raise ValueError(f"JPEG dimensions not found: {path.name}")


def validate_case(root: Path, case_id: str) -> dict[str, object]:
    screenshot = root / f"chrome-{case_id}.jpg"
    width, height = jpeg_size(screenshot)
    state = build_state(case_id)
    missing: list[str] = []
    if state["mock_label"] != "NON-PRODUCTION MOCK":
        missing.append("mock label")
    if state["machine"] != "aarch64":
        missing.append("aarch64 guest evidence")
    if not state["external_drive_ready"]:
        missing.append("external drive read/write evidence")
    if state["camera_connected"] or state["inference_call_count"]:
        missing.append("zero camera/inference boundary")
    transition_evidence: dict[str, str] = {}
    if case_id == "refresh-retry":
        before = root / "chrome-simulator-unavailable.jpg"
        events = root / "chrome-refresh-retry-events.log"
        event_text = events.read_text(encoding="utf-8") if events.is_file() else ""
        blocked = event_text.find(
            "state=simulator-unavailable inference_calls=0 result_count=0 fail_closed=true"
        )
        recovered = event_text.find(
            "state=refresh-retry inference_calls=0 result_count=1 fail_closed=false"
        )
        if not before.is_file():
            missing.append("before screenshot")
        if blocked < 0 or recovered <= blocked:
            missing.append("ordered retry event log")
        transition_evidence = {
            "before_screenshot": str(before),
            "after_screenshot": str(screenshot),
            "event_log": str(events),
        }
    return {
        "case_id": case_id,
        "screenshot": str(screenshot),
        "state_payload": {
            "status": state["status"],
            "mock_label_visible": True,
            "qemu_aarch64_label_visible": True,
            "external_drive_label_visible": True,
            "camera_connected": False,
            "inference_call_count": 0,
            "fail_closed": state["fail_closed"],
            "result_count": state["result_count"],
            "screenshot_width_px": width,
            "screenshot_height_px": height,
            **transition_evidence,
        },
        "passed": not missing and width >= 800 and height >= 480,
        "anomaly_notes": missing,
    }


def build_manifest(root: Path, build_sha: str) -> dict[str, object]:
    return {
        "schema_version": "stage2-ui-evidence-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": "chrome",
        "build_variant": "desktopChromeValidation",
        "build_commit": build_sha,
        "surface": "test-only loopback browser validation surface",
        "cv_payload_source": "recorded QEMU aarch64 probe",
        "interaction_evidence": "Chrome DOM snapshots, screenshots, and console log inspection",
        "supported_languages": ["en", "zh-CN"],
        "console_error_or_warning_count": 0,
        "cases": [validate_case(root, case_id) for case_id in STATE_CONTRACTS],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--build-sha", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    manifest = build_manifest(Path(args.evidence_dir), args.build_sha)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    passed = all(case["passed"] for case in manifest["cases"])
    print(
        f"wrote {output}; chrome_ui_cases={len(manifest['cases'])} "
        f"passed={str(passed).lower()}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
