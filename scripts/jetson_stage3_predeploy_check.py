#!/usr/bin/env python3
"""Stage 3 pre-deployment readiness check — run ON the Xavier NX.

Verifies, without faking anything, that the deployed Administrator runner is
configured and answering the way the Stage 3 checklist requires:

1. Environment fail-closed: APP_ENV=production, XAVIER_INFERENCE_MODE=real,
   bridge library and model directory exist on disk.
2. `GET /livez` answers (process liveness).
3. `GET /api/v2/admin-runner/health` (bearer from XAVIER_CHECK_BEARER) reports
   `model_loaded=true`, the configured model identity, and the current
   hardware-validation status.

The emitted JSON evidence file records exactly what was observed. It never
claims "passed" — hardware validation status changes only through the manual
procedure in jetson_runner/HARDWARE_VALIDATION.md with reviewed evidence.

Usage (on the device):
    XAVIER_CHECK_BEARER=<admin bearer> \
    python3 scripts/jetson_stage3_predeploy_check.py \
        --base-url http://127.0.0.1:8600 \
        --output /opt/giraffe/evidence/stage3_predeploy_check.json

Exit codes: 0 all checks green; 1 one or more checks failed; 2 usage error.
Stdlib-only; compatible with JetPack 5.x Python 3.8.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import socket
import sys
import urllib.error
import urllib.request


def _check(name, ok, detail):
    print("[{}] {} — {}".format("PASS" if ok else "FAIL", name, detail))
    return {"check": name, "ok": bool(ok), "detail": detail}


def _get_json(url, bearer=None, timeout=15):
    req = urllib.request.Request(url)
    if bearer:
        req.add_header("Authorization", "Bearer " + bearer)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8600")
    parser.add_argument("--output", default="stage3_predeploy_check.json")
    args = parser.parse_args()

    results = []

    # 1. Environment fail-closed configuration
    app_env = os.getenv("APP_ENV", "")
    results.append(_check(
        "env.app_env_production", app_env.lower() == "production",
        "APP_ENV={!r}".format(app_env),
    ))
    mode = os.getenv("XAVIER_INFERENCE_MODE", "")
    results.append(_check(
        "env.inference_mode_real", mode.lower() == "real",
        "XAVIER_INFERENCE_MODE={!r} (mock must be refused in production)".format(mode),
    ))
    bridge = os.getenv("XAVIER_MNN_BRIDGE_LIBRARY", "")
    results.append(_check(
        "env.bridge_library_exists", bool(bridge) and os.path.isfile(bridge),
        "XAVIER_MNN_BRIDGE_LIBRARY={!r}".format(bridge),
    ))
    model_dir = os.getenv("XAVIER_MNN_MODEL_DIR", "")
    results.append(_check(
        "env.model_dir_exists", bool(model_dir) and os.path.isdir(model_dir),
        "XAVIER_MNN_MODEL_DIR={!r}".format(model_dir),
    ))

    # 2. Liveness
    livez_ok = False
    try:
        status, _ = _get_json(args.base_url + "/livez")
        livez_ok = status == 200
        detail = "HTTP {}".format(status)
    except (urllib.error.URLError, socket.timeout, ValueError) as exc:
        detail = str(exc)
    results.append(_check("service.livez", livez_ok, detail))

    # 3. Signed health
    bearer = os.getenv("XAVIER_CHECK_BEARER")
    health = None
    if not bearer:
        results.append(_check(
            "service.health", False,
            "XAVIER_CHECK_BEARER not set; cannot query the signed health endpoint",
        ))
    else:
        try:
            status, health = _get_json(
                args.base_url + "/api/v2/admin-runner/health", bearer=bearer
            )
            payload = (health or {}).get("payload", health) or {}
            model = payload.get("model", {})
            results.append(_check(
                "service.health", status == 200, "HTTP {}".format(status)
            ))
            results.append(_check(
                "model.loaded", bool(model.get("model_loaded")),
                "model_loaded={!r} model={!r}".format(
                    model.get("model_loaded"), model.get("model_name")
                ),
            ))
            hv = payload.get("hardware_validation", {})
            # Informational, never asserted: only the manual procedure with
            # reviewed evidence may move this to passed.
            print("[INFO] hardware_validation.status = {!r} (evidence_ref={!r})".format(
                hv.get("status"), hv.get("evidence_ref")
            ))
        except (urllib.error.URLError, socket.timeout, ValueError) as exc:
            results.append(_check("service.health", False, str(exc)))

    all_ok = all(r["ok"] for r in results)
    evidence = {
        "schema_version": "stage3-predeploy-check-v1",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "hostname": socket.gethostname(),
        "base_url": args.base_url,
        "all_checks_passed": all_ok,
        "checks": results,
        "health_response": health,
        "note": (
            "Pre-deployment readiness observation only. This file cannot set "
            "hardware validation to passed and is not Stage 3 acceptance "
            "evidence; see jetson_runner/HARDWARE_VALIDATION.md."
        ),
    }
    with open(args.output, "w") as fh:
        json.dump(evidence, fh, indent=2, ensure_ascii=False)
    print("\nevidence written to {}".format(args.output))
    print("overall: {}".format("READY" if all_ok else "NOT READY"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
