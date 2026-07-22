#!/usr/bin/env python3
"""Stage 3 Group B real-device harness — run ON the Xavier NX.

Group B (docs/STAGE3_AB_TESTING_SPEC.md §2): Jetson CV + a remote VLM reached
through ``RemoteChatVlmInspectionProvider``
(``src/qc_model/production/remote_chat_provider.py``) over the restricted
tunnel described in ``docs/STAGE3_GROUP_B_REMOTE_ADAPTER.md``.

This script refuses to run (exit 1, no report written) unless the Stage 3
authorization gate is open (``scripts/ci/stage3_authorization_gate.py``) —
same as Group A.

GAP-08 (audit): the remote host currently has no endpoint that proves its
loaded model's revision/quantization/weight digest independently of what the
response itself claims. Until that exists, this script requires
``--remote-manifest-sha256`` to be supplied explicitly (obtained by the
operator from whatever manifest-verification the remote deployment provides
once it exists). Without it, the script still runs every case and records
real call evidence, but the emitted report's ``status`` is forced to
``"blocked"`` — never ``"passed"`` — because the model identity claim cannot
be independently verified yet. This is a deliberate fail-closed choice, not
an oversight: see docs/STAGE3_GROUP_B_REMOTE_ADAPTER.md §3.

Usage:
    python3 scripts/jetson_stage3_run_group_b.py \
        --vlm-base-url http://127.0.0.1:<local-tunnel-port> \
        --vlm-model qwen3-vl-4b-int4 \
        --cases cases.json \
        --model-backend cpu \
        [--remote-manifest-sha256 <sha256 from the remote's own manifest, once available>] \
        --output /opt/giraffe/evidence/stage3_ab_group_b_<timestamp>.json

``cases.json`` is a list of
``{"case_id", "image_path", "detection_point_code", "checkpoint_category",
"confirmed_content"}`` — one production-inspection request per case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_gate():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "stage3_gate", REPO_ROOT / "scripts" / "ci" / "stage3_authorization_gate.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_case(provider, case: dict, evidence_dir: Path) -> tuple[dict, bool]:
    from src.qc_model.production.provider import DetectionInspectionRequest

    request = DetectionInspectionRequest(
        detection_point_code=case["detection_point_code"],
        checkpoint_category=case.get("checkpoint_category", "visual_defect"),
        confirmed_content=case.get("confirmed_content", {}),
        image_references=[case["image_path"]],
    )

    request_ref = evidence_dir / f"{case['case_id']}_request.json"
    request_ref.write_text(
        json.dumps({
            "detection_point_code": request.detection_point_code,
            "checkpoint_category": request.checkpoint_category,
            "confirmed_content": request.confirmed_content,
            "image_references": request.image_references,
        }, indent=2),
        encoding="utf-8",
    )

    started = time.monotonic()
    try:
        result = provider.inspect(request)
        ok = True
        error = None
    except Exception as exc:  # noqa: BLE001 — recorded, never fabricated over
        result = None
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.monotonic() - started) * 1000)

    response_ref = evidence_dir / f"{case['case_id']}_response.json"
    response_ref.write_text(
        json.dumps(result.raw_response if result is not None else {"error": error}, indent=2),
        encoding="utf-8",
    )

    case_row = {
        "case_id": case["case_id"],
        "category": case.get("checkpoint_category", "visual_defect"),
        "input_ref": case["image_path"],
        "raw_model_output": json.dumps(result.raw_response) if result is not None else "",
        "parsed_result": result.raw_response if result is not None else {},
        "verdict": "reject" if not ok else ("pass" if result.disposition == "pass_recommended" else "reject"),
        "timing_ms": {"cv": 0, "inference": elapsed_ms, "parse": 0, "total": elapsed_ms},
        "passed": ok,
        "anomaly_notes": [] if ok else [error],
        "mock_flags": [],
        "request_ref": str(request_ref),
        "response_ref": str(response_ref),
    }
    return case_row, ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vlm-base-url", required=True)
    parser.add_argument("--vlm-model", required=True)
    parser.add_argument("--vlm-api-key", default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--cases", required=True)
    parser.add_argument(
        "--model-backend", required=True,
        choices=["cpu", "cuda", "opencl", "hybrid_cpu_cuda"],
        help="the remote backend as reported by its own health output — never assume cuda",
    )
    parser.add_argument(
        "--remote-manifest-sha256", default=None,
        help="SHA-256 of the remote's model manifest, if the remote deployment "
        "provides one (GAP-08). Omit to still run every case for evidence "
        "collection, but the report status is then forced to 'blocked'.",
    )
    parser.add_argument("--model-revision", default="unverified")
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-dir", default=None)
    args = parser.parse_args()

    gate = _load_gate()
    gate_result = gate.evaluate()
    print(gate_result.summary())
    if not gate_result.open:
        print("refusing to run Group B: Stage 3 authorization gate is closed", file=sys.stderr)
        return 1

    from src.qc_model.production.remote_chat_provider import RemoteChatVlmInspectionProvider

    provider = RemoteChatVlmInspectionProvider(
        base_url=args.vlm_base_url, model=args.vlm_model,
        api_key=args.vlm_api_key, timeout=args.timeout,
    )
    if not provider.is_configured:
        print("refusing to run Group B: provider is not configured (base_url/model missing)", file=sys.stderr)
        return 1

    with open(args.cases) as fh:
        cases = json.load(fh)

    output_path = Path(args.output)
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else output_path.parent / (output_path.stem + "_evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    report_cases = []
    call_evidence = []
    all_ok = True
    for case in cases:
        row, ok = run_case(provider, case, evidence_dir)
        report_cases.append(row)
        call_evidence.append({
            "case_id": row["case_id"],
            "raw_request_ref": row["request_ref"],
            "raw_response_ref": row["response_ref"],
        })
        all_ok = all_ok and ok
        print(f"[{'OK' if ok else 'FAIL'}] {case['case_id']}")

    identity_verified = bool(args.remote_manifest_sha256)
    if identity_verified:
        manifest_sha = args.remote_manifest_sha256
        status = "passed" if (all_ok and report_cases) else "failed"
    else:
        # No independent identity evidence yet (GAP-08) — record real call
        # evidence but refuse to claim acceptance.
        manifest_sha = "0" * 64
        status = "blocked"
        print(
            "\nWARNING: --remote-manifest-sha256 not supplied; remote model "
            "identity is unverified (GAP-08). Report status forced to "
            "'blocked' regardless of case outcomes. See "
            "docs/STAGE3_GROUP_B_REMOTE_ADAPTER.md §3.",
            file=sys.stderr,
        )

    report = {
        "schema_version": "sandbox-qc-report-stage3-ab-v1",
        "stage": 3,
        "status": status,
        "environment_declaration": "Xavier NX real device, Group B remote VLM path over restricted tunnel",
        "model_delta_note": "Group B calls a remote OpenAI-compatible chat endpoint through a restricted SSH tunnel; never a public interface.",
        "stage3_group": "B",
        "cv_execution_location": "jetson_local",
        "vlm_execution_location": "remote",
        "model": {
            "provider": "remote_chat_vlm",
            "name": args.vlm_model,
            "revision": args.model_revision,
            "quantization": "int4" if "int4" in args.vlm_model.lower() else "unspecified",
            "backend": args.model_backend,
            "manifest_sha256": manifest_sha,
        },
        "call_evidence": call_evidence,
        "network": {
            "tunnel_ready": all_ok or bool(report_cases),
            "remote_model_ready": all_ok,
        },
        "hardware_validation_status": "not_run",
        "production_eligible": False,
        "summary": {
            "case_count": len(report_cases),
            "passed_case_count": sum(1 for c in report_cases if c["passed"]),
            "model_call_count": sum(1 for c in report_cases if c["passed"]),
        },
        "acceptance": {},
        "cases": report_cases,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity_verified": identity_verified,
    }
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport written to {output_path}")
    return 0 if (all_ok and identity_verified) else 1


if __name__ == "__main__":
    sys.exit(main())
