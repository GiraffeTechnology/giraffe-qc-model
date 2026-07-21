"""Validate Android UI screenshots/UIAutomator dumps and emit the Stage 2 manifest."""
from __future__ import annotations

import argparse
import json
import struct
from datetime import datetime, timezone
from pathlib import Path


STATE_CONTRACTS = {
    "simulator-ready": {"status": "READY", "fail_closed": False, "result_count": 0},
    "simulated-capture": {
        "status": "FIXTURE LOADED",
        "fail_closed": False,
        "result_count": 0,
    },
    "cv-success": {"status": "CV COMPLETE", "fail_closed": False, "result_count": 1},
    "cv-anomaly": {
        "status": "REVIEW REQUIRED",
        "fail_closed": True,
        "result_count": 0,
    },
    "simulator-unavailable": {
        "status": "BLOCKED",
        "fail_closed": True,
        "result_count": 0,
    },
    "refresh-retry": {
        "status": "RETRY COMPLETE",
        "fail_closed": False,
        "result_count": 1,
    },
}


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as source:
        header = source.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"invalid PNG evidence: {path.name}")
    return struct.unpack(">II", header[16:24])


def validate_case(root: Path, case_id: str) -> dict[str, object]:
    contract = STATE_CONTRACTS[case_id]
    screenshot = root / f"{case_id}.png"
    hierarchy = root / f"{case_id}.xml"
    width, height = png_size(screenshot)
    xml = hierarchy.read_text(encoding="utf-8")
    required_text = ["NON-PRODUCTION MOCK", case_id, str(contract["status"]), "Inference calls: 0"]
    missing = [text for text in required_text if text not in xml]
    if case_id == "refresh-retry" and "Result count: 1" not in xml:
        missing.append("Result count: 1")
    if contract["fail_closed"] and "Fail closed: YES" not in xml:
        missing.append("Fail closed: YES")
    transition_evidence: dict[str, str] = {}
    if case_id == "refresh-retry":
        before_screenshot = root / "simulator-unavailable.png"
        event_log = root / "refresh-retry-events.log"
        events = event_log.read_text(encoding="utf-8") if event_log.is_file() else ""
        unavailable_position = events.find(
            "state=simulator-unavailable inference_calls=0 result_count=0 fail_closed=true"
        )
        recovered_position = events.find(
            "state=refresh-retry inference_calls=0 result_count=1 fail_closed=false"
        )
        if not before_screenshot.is_file():
            missing.append("simulator-unavailable before screenshot")
        if unavailable_position < 0 or recovered_position <= unavailable_position:
            missing.append("ordered unavailable-to-recovered event log")
        transition_evidence = {
            "before_screenshot": str(before_screenshot),
            "after_screenshot": str(screenshot),
            "event_log": str(event_log),
        }
    return {
        "case_id": case_id,
        "screenshot": str(screenshot),
        "ui_hierarchy": str(hierarchy),
        "state_payload": {
            "status": contract["status"],
            "mock_label_visible": "NON-PRODUCTION MOCK" in xml,
            "qemu_aarch64_label_visible": "QEMU aarch64" in xml,
            "inference_call_count": 0,
            "fail_closed": contract["fail_closed"],
            "result_count": contract["result_count"],
            "screenshot_width_px": width,
            "screenshot_height_px": height,
            **transition_evidence,
        },
        "passed": not missing and width >= 800 and height >= 480,
        "anomaly_notes": [f"missing visible text: {text}" for text in missing],
    }


def build_manifest(root: Path, build_sha: str) -> dict[str, object]:
    return {
        "schema_version": "stage2-ui-evidence-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": "android_x86_64_emulator",
        "build_variant": "padLocalDebug",
        "build_commit": build_sha,
        "surface": "debug-only Compose evidence activity; absent from release builds",
        "cv_payload_source": "separately verified QEMU aarch64 probe",
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
    print(f"wrote {output}; ui_cases={len(manifest['cases'])} passed={str(passed).lower()}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
