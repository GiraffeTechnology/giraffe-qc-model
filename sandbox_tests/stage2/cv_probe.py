"""Capture deterministic standalone-CV evidence for one execution architecture."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy

from sandbox_tests.stage1.cv_stage import run_cv_stage


ROOT = Path(__file__).parents[2]


def load_cv_cases(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("Stage 2 source cases must be an array")
    cases = [case for case in value if case.get("case_type") == "real_inference"]
    if not cases:
        raise ValueError("Stage 2 requires real-inference source cases for CV inputs")
    return cases


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_probe(cases_path: str | Path) -> dict[str, Any]:
    cases = load_cv_cases(cases_path)
    results: list[dict[str, Any]] = []
    for case in cases:
        image_path = ROOT / case["input_ref"]
        results.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "input_ref": case["input_ref"],
                "input_sha256": _sha256(image_path),
                "cv_result": run_cv_stage(image_path, case["cv_config"]),
            }
        )
    return {
        "schema_version": "stage2-cv-probe-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runtime": {
            "machine": platform.machine().lower(),
            "system": platform.system(),
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "numpy": numpy.__version__,
            "executable": Path(sys.executable).name,
        },
        "model_invoked": False,
        "camera_connected": False,
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="sandbox_tests/stage1/cases.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_probe(args.cases), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output}; model_invoked=false camera_connected=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
