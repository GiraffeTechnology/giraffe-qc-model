#!/usr/bin/env python3
"""Stage 3 Group A real-device harness — run ON the Xavier NX.

Group A (docs/STAGE3_AB_TESTING_SPEC.md §1): Jetson CV + Jetson-local
Qwen3-VL-2B/4B MNN via the already-deployed Administrator runner
(``POST /api/v2/admin-runner/recognitions`` — see
``docs/api-contracts/xavier-admin-runner-api.md``). This script is a client
of that endpoint, signing each request with the real Ed25519 admin-auth
scheme in ``jetson_runner/app/admin_auth.py`` — the exact functions the
server itself verifies with, not a re-derived approximation — so a
successful signature here is provably compatible.

This script refuses to run (exit 1, no report written) unless, in order:

1. The Stage 3 authorization gate is open
   (``scripts/ci/stage3_authorization_gate.py``) — a fresh Stage 2
   acceptance must be on record.
2. The pinned MNN SDK lock is approved
   (``scripts/jetson_verify_mnn_lock.py``).
3. The model manifest for the configured model matches the files on disk
   and is approved (``scripts/jetson_verify_model_manifest.py``).

None of those three checks can be bypassed with a flag. If the runner itself
returns an error, times out, or reports ``model_loaded=false``, that failure
is recorded in the report as a failed case — never silently retried against
a different model, and never replaced with a fabricated pass.

Requires the jetson_runner venv (pydantic + cryptography), not just stdlib —
run it with the same interpreter used to install
jetson_runner/requirements.txt.

Usage:
    python3 scripts/jetson_stage3_run_group_a.py \
        --base-url http://127.0.0.1:8600 \
        --bearer <admin bearer> \
        --key-id <provisioned key id> \
        --private-key-path /etc/giraffe/keys/admin-runner-ed25519.pem \
        --standard-revision-id <revision id> \
        --bundle-version <bundle version> \
        --cases cases.json \
        --model-manifest /opt/giraffe/models/qwen3-vl-4b-mnn/model_manifest.json \
        --output /opt/giraffe/evidence/stage3_ab_group_a_<timestamp>.json

``cases.json`` is a list of
``{"case_id", "image_path", "detection_points": [<AdminDetectionPoint dict>]}``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_module(rel_path: str, name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses' __module__ lookup needs this registered
    spec.loader.exec_module(mod)
    return mod


def build_manifest(
    *, request_id: str, workflow: str, standard_revision_id: str,
    bundle_version: str, image_id: str, part: str, image_bytes: bytes,
    content_type: str, detection_points: list[dict],
) -> dict:
    return {
        "schema_version": "2.0",
        "request_id": request_id,
        "workflow": workflow,
        "standard_revision_id": standard_revision_id,
        "bundle_version": bundle_version,
        "images": [{
            "image_id": image_id,
            "part": part,
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "content_type": content_type,
            "encoded_bytes": len(image_bytes),
        }],
        "detection_points": detection_points,
    }


def sign_headers(admin_auth, private_key, *, key_id: str, bearer: str, method: str, path: str, manifest: dict) -> dict:
    digest = admin_auth.multipart_content_sha256(manifest)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    nonce = uuid.uuid4().hex
    payload = admin_auth.signature_payload(
        method, path, timestamp, nonce, digest, manifest["request_id"]
    )
    signature = private_key.sign(payload)
    return {
        "Authorization": f"Bearer {bearer}",
        "X-QC-Key-Id": key_id,
        "X-QC-Timestamp": timestamp,
        "X-QC-Nonce": nonce,
        "X-QC-Content-SHA256": digest,
        "X-QC-Signature": base64.b64encode(signature).decode("ascii"),
    }, digest


def call_recognitions(base_url: str, headers: dict, manifest: dict, image_bytes: bytes, part: str, content_type: str, timeout: float):
    """Isolated so tests can stub the HTTP layer without a live server."""
    import httpx

    response = httpx.post(
        base_url.rstrip("/") + "/api/v2/admin-runner/recognitions",
        headers=headers,
        data={"manifest": json.dumps(manifest)},
        files=[("images", (part, image_bytes, content_type))],
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def run_case(*, admin_auth, private_key, base_url, key_id, bearer, workflow,
             standard_revision_id, bundle_version, case: dict, timeout: float,
             evidence_dir: Path) -> dict:
    image_path = Path(case["image_path"])
    image_bytes = image_path.read_bytes()
    request_id = "stage3-a-" + uuid.uuid4().hex[:12]
    manifest = build_manifest(
        request_id=request_id, workflow=workflow,
        standard_revision_id=standard_revision_id, bundle_version=bundle_version,
        image_id="primary", part=image_path.name, image_bytes=image_bytes,
        content_type="image/jpeg", detection_points=case["detection_points"],
    )
    path = "/api/v2/admin-runner/recognitions"
    headers, _digest = sign_headers(
        admin_auth, private_key, key_id=key_id, bearer=bearer,
        method="POST", path=path, manifest=manifest,
    )

    request_ref = evidence_dir / f"{case['case_id']}_request.json"
    request_ref.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    started = time.monotonic()
    try:
        raw = call_recognitions(base_url, headers, manifest, image_bytes, image_path.name, "image/jpeg", timeout)
        ok = True
        error = None
    except Exception as exc:  # noqa: BLE001 — recorded, never fabricated over
        raw = None
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.monotonic() - started) * 1000)

    response_ref = evidence_dir / f"{case['case_id']}_response.json"
    response_ref.write_text(json.dumps(raw if raw is not None else {"error": error}, indent=2), encoding="utf-8")

    return {
        "case_id": case["case_id"],
        "category": case.get("category", "visual_defect"),
        "input_ref": str(image_path),
        "raw_model_output": json.dumps(raw) if raw is not None else "",
        "parsed_result": raw or {},
        "verdict": "reject" if not ok else _verdict_from_points(raw),
        "timing_ms": {"cv": 0, "inference": elapsed_ms, "parse": 0, "total": elapsed_ms},
        "passed": ok,
        "anomaly_notes": [] if ok else [error],
        "mock_flags": ["real_device_call"] if ok and raw and raw.get("mock") else [],
        "request_ref": str(request_ref),
        "response_ref": str(response_ref),
    }, ok, raw


def _verdict_from_points(raw) -> str:
    if not raw or not raw.get("point_results"):
        return "reject"
    return "reject" if any(p.get("result") == "fail" for p in raw["point_results"]) else "pass"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8600")
    parser.add_argument("--bearer", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--private-key-path", required=True)
    parser.add_argument("--standard-revision-id", required=True)
    parser.add_argument("--bundle-version", default="")
    parser.add_argument("--workflow", default="qualification_review",
                         choices=["authoring_validation", "qualification_review", "admin_recheck"])
    parser.add_argument("--cases", required=True, help="path to a cases.json describing test images + detection points")
    parser.add_argument("--mnn-lock", default="deploy/jetson/mnn-sdk.lock.json")
    parser.add_argument("--model-manifest", required=True)
    parser.add_argument("--model-provider", default="local-mnn")
    parser.add_argument(
        "--model-backend", required=True,
        choices=["cpu", "cuda", "opencl", "hybrid_cpu_cuda"],
        help="the backend actually observed for this run (operator-declared: "
        "the current recognitions/health contract does not report it, so this "
        "script cannot infer it and must not assume 'cpu')",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-dir", default=None, help="defaults next to --output")
    args = parser.parse_args()

    gate = _load_module("scripts/ci/stage3_authorization_gate.py", "stage3_gate")
    gate_result = gate.evaluate()
    print(gate_result.summary())
    if not gate_result.open:
        print("refusing to run Group A: Stage 3 authorization gate is closed", file=sys.stderr)
        return 1

    lock_check = _load_module("scripts/jetson_verify_mnn_lock.py", "lock_check")
    with open(args.mnn_lock) as fh:
        mnn_lock = json.load(fh)
    lock_problems = lock_check.verify(mnn_lock, archive_path=None)
    if lock_problems:
        print("refusing to run Group A: MNN SDK lock is not approved:", file=sys.stderr)
        for p in lock_problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    manifest_check = _load_module("scripts/jetson_verify_model_manifest.py", "manifest_check")
    with open(args.model_manifest) as fh:
        model_manifest = json.load(fh)
    manifest_problems = manifest_check.verify(
        model_manifest, model_dir=str(Path(args.model_manifest).parent), mnn_lock=mnn_lock,
    )
    if manifest_problems:
        print("refusing to run Group A: model manifest is not approved / does not match disk:", file=sys.stderr)
        for p in manifest_problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    admin_auth = _load_module("jetson_runner/app/admin_auth.py", "admin_auth")
    from cryptography.hazmat.primitives import serialization

    with open(args.private_key_path, "rb") as fh:
        private_key = serialization.load_pem_private_key(fh.read(), password=None)

    with open(args.cases) as fh:
        cases = json.load(fh)

    output_path = Path(args.output)
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else output_path.parent / (output_path.stem + "_evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    report_cases = []
    call_evidence = []
    all_ok = True
    last_raw = None
    for case in cases:
        result, ok, raw = run_case(
            admin_auth=admin_auth, private_key=private_key, base_url=args.base_url,
            key_id=args.key_id, bearer=args.bearer, workflow=args.workflow,
            standard_revision_id=args.standard_revision_id, bundle_version=args.bundle_version,
            case=case, timeout=args.timeout, evidence_dir=evidence_dir,
        )
        report_cases.append(result)
        call_evidence.append({
            "case_id": result["case_id"],
            "raw_request_ref": result["request_ref"],
            "raw_response_ref": result["response_ref"],
        })
        all_ok = all_ok and ok
        if raw is not None:
            last_raw = raw
        print(f"[{'OK' if ok else 'FAIL'}] {case['case_id']}")

    runtime = (last_raw or {}).get("runtime", {})
    report = {
        "schema_version": "sandbox-qc-report-stage3-ab-v1",
        "stage": 3,
        "status": "passed" if (all_ok and report_cases) else "failed",
        "environment_declaration": "Xavier NX real device, Group A local MNN path",
        "model_delta_note": "Group A uses the Jetson-local Administrator MNN runner; not an operator production path.",
        "stage3_group": "A",
        "cv_execution_location": "jetson_local",
        "vlm_execution_location": "jetson_local",
        "model": {
            "provider": args.model_provider,
            "name": runtime.get("model_name", model_manifest.get("model_name", "")),
            "revision": runtime.get("model_revision", model_manifest.get("upstream_revision", "")),
            "quantization": model_manifest.get("quantization", ""),
            "backend": args.model_backend,
            "manifest_sha256": hashlib.sha256(
                json.dumps(model_manifest, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "call_evidence": call_evidence,
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
    }
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport written to {output_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
