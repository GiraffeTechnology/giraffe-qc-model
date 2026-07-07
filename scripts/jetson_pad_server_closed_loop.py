#!/usr/bin/env python3
"""Jetson loopback test: one device acts as Pad and Server.

The goal is to exercise the product loop while keeping the LLM/VLM model fixed:

    simulated/CV-module photo -> Pad request -> Server inspection -> Pad result

Both the Pad role and Server role point at the same local
Qwen3-VL-2B-Instruct-MNN asset directory. The current repository does not wire
Jetson local MNN VLM inference yet, so the server-side inspection step uses the
same deterministic OpenCV visual comparator used by the Jetson smoke test.

This is a test-machine loopback. It is deliberately not marked production
eligible because it uses one Jetson to simulate two deployment roles and may use
still-image files instead of a real CV module capture.
"""
from __future__ import print_function

import argparse
import json
import os
import socket
import sys
import time
import uuid

import jetson_photo_production_smoke as smoke


MODEL_NAME = "Qwen3-VL-2B-Instruct-MNN"
MODEL_DIR = "/home/giraffe/work/qwen3-vl-2b-mnn"


def write_json(path, data):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)


def read_json(path):
    with open(path) as fh:
        return json.load(fh)


def build_pad_request(args, run_id, run_dir):
    capture_photo = os.path.abspath(args.capture)
    capture_metadata = {
        "capture_source": "file",
        "source_role": "cv_module_simulated_photo",
    }
    if args.capture_source == "camera":
        capture_photo, camera_metadata = smoke.capture_from_camera(args, run_dir)
        capture_metadata.update(camera_metadata)

    request = {
        "schema_version": "giraffe-pad-server-loopback-request-v1",
        "run_id": run_id,
        "created_at": smoke.now_iso(),
        "pad_role": {
            "device_id": args.pad_device_id,
            "host": socket.gethostname(),
            "runtime_profile": "tablet_mnn",
            "model_name": MODEL_NAME,
            "model_dir": args.model_dir,
        },
        "server_role": {
            "host": socket.gethostname(),
            "runtime_profile": "server_loopback_same_model",
            "model_name": MODEL_NAME,
            "model_dir": args.model_dir,
        },
        "context": {
            "tenant_id": args.tenant_id,
            "sku_id": args.sku_id,
            "station_id": args.station_id,
            "inspection_id": args.inspection_id or run_id,
        },
        "photos": {
            "standard_photo": os.path.abspath(args.standard),
            "capture_photo": capture_photo,
            "capture_metadata": capture_metadata,
        },
        "qc_points": [
            {
                "qc_point_id": "visual_match",
                "qc_point_code": "VISUAL_MATCH",
                "name": "Visual match against approved standard photo",
                "description": "Compare the captured production photo against the approved standard photo.",
            }
        ],
        "transport": "local_file_loopback",
        "deployment_scope": {
            "class": "test_machine_pad_server_loopback",
            "production_eligible": False,
            "hardware_role": "one Jetson Xavier NX simulates Pad and Server",
            "configuration": "simulated photo input and local file transport",
        },
    }
    write_json(os.path.join(run_dir, "pad_request.json"), request)
    return request


def run_server_inspection(request, args, run_dir):
    model_assets = smoke.validate_model_dir(args.model_dir, args.verify_hash)
    photos = request["photos"]
    result = smoke.compare_images(
        photos["standard_photo"],
        photos["capture_photo"],
        os.path.join(run_dir, "server_evidence"),
    )

    response = {
        "schema_version": "giraffe-pad-server-loopback-response-v1",
        "run_id": request["run_id"],
        "created_at": smoke.now_iso(),
        "server_role": request["server_role"],
        "model_policy": {
            "llm_vlm_model_switched": False,
            "pad_model_name": request["pad_role"]["model_name"],
            "server_model_name": request["server_role"]["model_name"],
            "pad_model_dir": request["pad_role"]["model_dir"],
            "server_model_dir": request["server_role"]["model_dir"],
        },
        "runtime": {
            "engine": "server_loopback_cv_comparator",
            "local_qwen_mnn_inference": False,
            "note": (
                "Loopback keeps the LLM/VLM asset fixed on Jetson. "
                "The current repo still lacks a wired local MNN VLM inference provider."
            ),
        },
        "model_assets": model_assets,
        "inspection": result,
        "human_final_decision_required": True,
        "deployment_scope": request["deployment_scope"],
    }
    write_json(os.path.join(run_dir, "server_response.json"), response)
    return response


def build_pad_final_view(request, response, run_dir):
    inspection = response["inspection"]
    final_view = {
        "schema_version": "giraffe-pad-final-view-v1",
        "run_id": request["run_id"],
        "created_at": smoke.now_iso(),
        "pad_device_id": request["pad_role"]["device_id"],
        "inspection_id": request["context"]["inspection_id"],
        "overall_result": inspection["overall_result"],
        "similarity_score": inspection["similarity_score"],
        "severity": inspection["severity"],
        "deviations": inspection["deviations"],
        "evidence_files": inspection["evidence_files"],
        "human_final_decision_required": response["human_final_decision_required"],
        "model_name": request["pad_role"]["model_name"],
        "server_used_same_model": (
            request["pad_role"]["model_name"] == response["model_policy"]["server_model_name"]
            and request["pad_role"]["model_dir"] == response["model_policy"]["server_model_dir"]
        ),
        "production_eligible": response["deployment_scope"]["production_eligible"],
    }
    write_json(os.path.join(run_dir, "pad_final_view.json"), final_view)
    return final_view


def run_loop(args):
    run_id = uuid.uuid4().hex
    run_dir = os.path.abspath(os.path.join(args.out_dir, run_id))
    if not os.path.isdir(run_dir):
        os.makedirs(run_dir)

    started = time.time()
    request = build_pad_request(args, run_id, run_dir)
    response = run_server_inspection(request, args, run_dir)
    final_view = build_pad_final_view(request, response, run_dir)

    closed_loop_ok = bool(
        response["model_assets"]["verified"]
        and final_view["server_used_same_model"]
        and final_view["overall_result"] in ("pass", "needs_fix", "reject")
    )
    report = {
        "schema_version": "giraffe-jetson-pad-server-loopback-report-v1",
        "run_id": run_id,
        "created_at": smoke.now_iso(),
        "elapsed_ms": int((time.time() - started) * 1000),
        "closed_loop_ok": closed_loop_ok,
        "roles_on_same_jetson": True,
        "deployment_scope": request["deployment_scope"],
        "production_eligible": False,
        "llm_vlm_model_switched": False,
        "model_name": MODEL_NAME,
        "model_dir": args.model_dir,
        "artifacts": {
            "pad_request": os.path.join(run_dir, "pad_request.json"),
            "server_response": os.path.join(run_dir, "server_response.json"),
            "pad_final_view": os.path.join(run_dir, "pad_final_view.json"),
        },
        "summary": {
            "overall_result": final_view["overall_result"],
            "similarity_score": final_view["similarity_score"],
            "model_assets_verified": response["model_assets"]["verified"],
            "server_used_same_model": final_view["server_used_same_model"],
            "capture_source": request["photos"]["capture_metadata"]["capture_source"],
            "local_qwen_mnn_inference": response["runtime"]["local_qwen_mnn_inference"],
        },
    }
    report_path = os.path.join(run_dir, "closed_loop_report.json")
    write_json(report_path, report)
    report["report_path"] = report_path
    return report


def parse_args(argv):
    here = os.getcwd()
    parser = argparse.ArgumentParser(description="Run Jetson Pad+Server same-model loopback test.")
    parser.add_argument("--standard", default=os.path.join(here, "tests", "fixtures", "red_square.png"))
    parser.add_argument("--capture", default=os.path.join(here, "tests", "fixtures", "red_square_with_dot.png"))
    parser.add_argument("--capture-source", choices=["file", "camera"], default="file")
    parser.add_argument("--model-dir", default=MODEL_DIR)
    parser.add_argument("--out-dir", default="/home/giraffe/work/giraffe-qc-model/artifacts/jetson_pad_server_loop")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--sku-id", default="demo-sku")
    parser.add_argument("--station-id", default="jetson-loopback")
    parser.add_argument("--inspection-id", default="")
    parser.add_argument("--pad-device-id", default="jetson-as-pad-001")
    parser.add_argument("--verify-hash", action="store_true")
    parser.add_argument("--camera-backend", choices=["auto", "csi", "v4l2"], default="auto")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--camera-sensor-id", type=int, default=0)
    parser.add_argument("--camera-width", type=int, default=1280)
    parser.add_argument("--camera-height", type=int, default=720)
    parser.add_argument("--camera-fps", type=int, default=30)
    parser.add_argument("--camera-flip-method", type=int, default=0)
    parser.add_argument("--camera-warmup-frames", type=int, default=5)
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    try:
        report = run_loop(args)
    except Exception as exc:
        print(json.dumps({
            "schema_version": "giraffe-jetson-pad-server-loopback-report-v1",
            "created_at": smoke.now_iso(),
            "closed_loop_ok": False,
            "error": "%s: %s" % (type(exc).__name__, exc),
        }, indent=2, sort_keys=True))
        return 2
    print(json.dumps({
        "closed_loop_ok": report["closed_loop_ok"],
        "overall_result": report["summary"]["overall_result"],
        "similarity_score": report["summary"]["similarity_score"],
        "model_assets_verified": report["summary"]["model_assets_verified"],
        "server_used_same_model": report["summary"]["server_used_same_model"],
        "llm_vlm_model_switched": report["llm_vlm_model_switched"],
        "local_qwen_mnn_inference": report["summary"]["local_qwen_mnn_inference"],
        "production_eligible": report["production_eligible"],
        "deployment_class": report["deployment_scope"]["class"],
        "report_path": report["report_path"],
    }, indent=2, sort_keys=True))
    return 0 if report["closed_loop_ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
