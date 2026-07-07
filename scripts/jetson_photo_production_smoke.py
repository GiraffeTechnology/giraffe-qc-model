#!/usr/bin/env python3
"""Jetson photo-input production smoke test.

This script is intentionally Python 3.6 compatible because the stock Jetson
Xavier NX L4T image ships Python 3.6. It validates the local Qwen MNN assets,
accepts a still image from the Edge CV module path or captures one from the
Jetson camera stack, runs a deterministic OpenCV visual comparison, writes
evidence images, and emits an auditable JSON report.

It does not claim to run Qwen MNN inference. The current giraffe-qc-model repo
has no wired local MNN runtime provider on Jetson yet, so this is a production
shape smoke test for photo input.

This is test-hardware validation, not a real production deployment. In test
mode, still-image files may replace CV module input.
"""
from __future__ import print_function

import argparse
import datetime as _dt
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid

import cv2
import numpy as np


WIDTH = 320
HEIGHT = 240

COLOUR_REJECT = 0.40
COLOUR_WARN = 0.72
DEFECT_NOISE = 0.004
DEFECT_WARN = 0.015
DEFECT_REJECT = 0.07
SIM_PASS = 0.86
SIM_FIX = 0.60

EXPECTED_MODEL_FILES = {
    "llm.mnn": {"size": 462464},
    "visual.mnn": {"size": 502512},
    "llm.mnn.weight": {
        "size": 1231860194,
        "sha256": "1554f9ce71743b56c2d7fba4cb0c2a31c7cddf4f21e1a2ff5a2e85b9a316a29f",
    },
    "visual.mnn.weight": {
        "size": 238226780,
        "sha256": "9feb04848cafad1117a510b43d6c2b58d6c31bef1040598156d266f9b42f581f",
    },
    "tokenizer.txt": {
        "size": 3193555,
        "sha256": "7119de4966cc6a8ae87d7f083e65b315282d06c3122fdd41ce783fdd2d3c1ca2",
    },
}


def now_iso():
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def validate_model_dir(model_dir, verify_hash):
    files = []
    ok = True
    for name in sorted(EXPECTED_MODEL_FILES):
        expected = EXPECTED_MODEL_FILES[name]
        path = os.path.join(model_dir, name)
        item = {
            "name": name,
            "path": path,
            "exists": os.path.isfile(path),
            "expected_size": expected.get("size"),
            "actual_size": None,
            "size_ok": False,
            "sha256_expected": expected.get("sha256"),
            "sha256_actual": None,
            "sha256_ok": None,
        }
        if item["exists"]:
            item["actual_size"] = os.path.getsize(path)
            item["size_ok"] = item["actual_size"] == item["expected_size"]
            if verify_hash and expected.get("sha256"):
                item["sha256_actual"] = sha256_file(path)
                item["sha256_ok"] = item["sha256_actual"] == expected["sha256"]
        ok = ok and item["exists"] and item["size_ok"]
        if verify_hash and expected.get("sha256"):
            ok = ok and item["sha256_ok"]
        files.append(item)
    return {"model_dir": model_dir, "verified": ok, "hash_checked": bool(verify_hash), "files": files}


def load_image(path, label):
    img = cv2.imread(path)
    if img is None:
        raise RuntimeError("%s is not a readable image: %s" % (label, path))
    return img


def csi_pipeline(sensor_id, width, height, fps, flip_method):
    return (
        "nvarguscamerasrc sensor-id=%d ! "
        "video/x-raw(memory:NVMM), width=(int)%d, height=(int)%d, "
        "framerate=(fraction)%d/1, format=(string)NV12 ! "
        "nvvidconv flip-method=%d ! "
        "video/x-raw, width=(int)%d, height=(int)%d, format=(string)BGRx ! "
        "videoconvert ! video/x-raw, format=(string)BGR ! "
        "appsink drop=true max-buffers=1"
    ) % (sensor_id, width, height, fps, flip_method, width, height)


def open_camera(args, backend):
    if backend == "csi":
        pipeline = csi_pipeline(
            args.camera_sensor_id,
            args.camera_width,
            args.camera_height,
            args.camera_fps,
            args.camera_flip_method,
        )
        return cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER), pipeline
    if backend == "v4l2":
        cap = cv2.VideoCapture(args.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.camera_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.camera_height)
        cap.set(cv2.CAP_PROP_FPS, args.camera_fps)
        return cap, "/dev/video%d" % args.camera_index
    raise RuntimeError("unknown camera backend: %s" % backend)


def capture_from_camera(args, evidence_dir):
    backends = []
    if args.camera_backend == "auto":
        backends = ["csi", "v4l2"]
    else:
        backends = [args.camera_backend]

    errors = []
    for backend in backends:
        cap, source = open_camera(args, backend)
        try:
            if not cap.isOpened():
                errors.append("%s not opened (%s)" % (backend, source))
                continue

            frame = None
            for _ in range(max(1, args.camera_warmup_frames)):
                ok, candidate = cap.read()
                if ok and candidate is not None:
                    frame = candidate
            ok, candidate = cap.read()
            if ok and candidate is not None:
                frame = candidate
            if frame is None:
                errors.append("%s opened but no frame read (%s)" % (backend, source))
                continue

            if not os.path.isdir(evidence_dir):
                os.makedirs(evidence_dir)
            capture_path = os.path.join(evidence_dir, "cv_module_capture.jpg")
            if not cv2.imwrite(capture_path, frame):
                raise RuntimeError("failed to write captured frame: %s" % capture_path)
            return capture_path, {
                "capture_source": "camera",
                "camera_backend": backend,
                "camera_source": source,
                "camera_width": int(frame.shape[1]),
                "camera_height": int(frame.shape[0]),
            }
        finally:
            cap.release()

    raise RuntimeError("camera capture failed: " + "; ".join(errors))


def resize(img):
    return cv2.resize(img, (WIDTH, HEIGHT))


def colour_score(img1, img2):
    h1 = cv2.cvtColor(resize(img1), cv2.COLOR_BGR2HSV)
    h2 = cv2.cvtColor(resize(img2), cv2.COLOR_BGR2HSV)
    hist1 = cv2.calcHist([h1], [0, 1], None, [50, 60], [0, 180, 0, 256])
    hist2 = cv2.calcHist([h2], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist1, hist1)
    cv2.normalize(hist2, hist2)
    dist = float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_BHATTACHARYYA))
    return float(max(0.0, 1.0 - dist))


def struct_score(img1, img2):
    g1 = cv2.cvtColor(resize(img1), cv2.COLOR_BGR2GRAY).astype(np.float32)
    g2 = cv2.cvtColor(resize(img2), cv2.COLOR_BGR2GRAY).astype(np.float32)
    s1 = float(np.std(g1))
    s2 = float(np.std(g2))
    if s1 < 3.0 and s2 < 3.0:
        return float(max(0.0, 1.0 - abs(g1.mean() - g2.mean()) / 128.0))
    if s1 < 3.0 or s2 < 3.0:
        return float(max(0.0, 1.0 - float(np.mean(np.abs(g1 - g2))) / 128.0))
    corr = float(np.mean((g1 - g1.mean()) * (g2 - g2.mean())) / (s1 * s2))
    return float(np.clip((corr + 1.0) / 2.0, 0.0, 1.0))


def orb_score(img1, img2):
    orb = cv2.ORB_create(nfeatures=500)
    g1 = cv2.cvtColor(resize(img1), cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(resize(img2), cv2.COLOR_BGR2GRAY)
    kp1, des1 = orb.detectAndCompute(g1, None)
    kp2, des2 = orb.detectAndCompute(g2, None)
    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return 0.0, False
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    raw = bf.knnMatch(des1, des2, k=2)
    good = [m for m, n in raw if m.distance < 0.75 * n.distance]
    return min(1.0, len(good) / float(max(len(kp1), len(kp2)))), True


def pixel_score(img1, img2):
    r1 = resize(img1).astype(np.float32) / 255.0
    r2 = resize(img2).astype(np.float32) / 255.0
    return float(max(0.0, 1.0 - 4.0 * float(np.mean(np.abs(r1 - r2)))))


def loc(cx, cy):
    v = "top" if cy < HEIGHT // 3 else ("bottom" if cy > 2 * HEIGHT // 3 else "center")
    h = "left" if cx < WIDTH // 3 else ("right" if cx > 2 * WIDTH // 3 else "center")
    if v == "center" and h == "center":
        return "center"
    if v == "center":
        return h
    if h == "center":
        return v
    return "%s-%s" % (v, h)


def detect_defects(std, prod):
    diff = cv2.absdiff(resize(std), resize(prod))
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    clean = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)
    found = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = found[0] if len(found) == 2 else found[1]
    total = WIDTH * HEIGHT
    result = []
    for c in cnts:
        area = cv2.contourArea(c)
        ratio = area / float(total)
        if ratio < DEFECT_NOISE:
            continue
        x, y, w, h = cv2.boundingRect(c)
        result.append({
            "area_ratio": round(ratio, 4),
            "bbox": [int(x), int(y), int(w), int(h)],
            "location": loc(x + w // 2, y + h // 2),
            "field": "surface",
        })
    return result, clean


def deviations(colour, struct, defects):
    out = []
    if colour < COLOUR_WARN:
        out.append({
            "field": "colour",
            "expected": "match standard",
            "actual": "similarity %.0f%%" % (colour * 100.0),
            "severity": "high" if colour < COLOUR_REJECT else "medium",
        })
    if struct < 0.72:
        out.append({
            "field": "structure",
            "expected": "match standard",
            "actual": "similarity %.0f%%" % (struct * 100.0),
            "severity": "medium",
        })
    for d in defects:
        out.append({
            "field": d["field"],
            "expected": "no defect",
            "actual": "defect at %s, area %.1f%%" % (d["location"], d["area_ratio"] * 100.0),
            "severity": "high" if d["area_ratio"] >= DEFECT_REJECT else "medium",
        })
    return out


def compare_images(standard_path, capture_path, evidence_dir):
    t0 = time.time()
    std = load_image(standard_path, "standard")
    prod = load_image(capture_path, "capture")

    colour = colour_score(std, prod)
    struct = struct_score(std, prod)
    orb, has_orb = orb_score(std, prod)
    pixel = pixel_score(std, prod)
    defects, mask = detect_defects(std, prod)

    if has_orb:
        sim = 0.25 * colour + 0.30 * struct + 0.25 * orb + 0.20 * pixel
    else:
        sim = 0.38 * colour + 0.38 * struct + 0.24 * pixel
    sim = round(float(np.clip(sim, 0.0, 1.0)), 4)

    defect_ratio = sum([d["area_ratio"] for d in defects])
    if sim >= SIM_PASS:
        verdict, severity = "pass", "low"
    elif sim >= SIM_FIX:
        verdict, severity = "needs_fix", "low" if sim >= 0.75 else "medium"
    else:
        verdict, severity = "reject", "high"

    if colour < COLOUR_REJECT:
        verdict, severity = "reject", "high"
    elif defect_ratio >= DEFECT_REJECT:
        verdict, severity = "reject", "high"
    elif defect_ratio >= DEFECT_WARN and verdict == "pass":
        verdict, severity = "needs_fix", "low"

    if not os.path.isdir(evidence_dir):
        os.makedirs(evidence_dir)
    mask_path = os.path.join(evidence_dir, "diff_mask.png")
    overlay_path = os.path.join(evidence_dir, "capture_overlay.png")
    cv2.imwrite(mask_path, mask)
    overlay = resize(prod).copy()
    for d in defects:
        x, y, w, h = d["bbox"]
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 255), 2)
    cv2.imwrite(overlay_path, overlay)

    return {
        "overall_result": verdict,
        "severity": severity,
        "similarity_score": sim,
        "signals": {
            "colour": round(float(colour), 4),
            "structure": round(float(struct), 4),
            "orb": round(float(orb), 4) if has_orb else None,
            "pixel": round(float(pixel), 4),
            "defect_ratio": round(float(defect_ratio), 4),
        },
        "defects": defects,
        "deviations": deviations(colour, struct, defects),
        "evidence_files": {
            "diff_mask": mask_path,
            "capture_overlay": overlay_path,
        },
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def git_commit(repo_dir):
    try:
        out = subprocess.check_output(["git", "-C", repo_dir, "rev-parse", "HEAD"])
        return out.decode("utf-8").strip()
    except Exception:
        return None


def build_report(args):
    run_id = uuid.uuid4().hex
    out_dir = os.path.abspath(args.out_dir)
    evidence_dir = os.path.join(out_dir, run_id)
    if not os.path.isdir(evidence_dir):
        os.makedirs(evidence_dir)

    capture_path = args.capture
    capture_metadata = {"capture_source": "file", "camera_backend": None}
    if args.capture_source == "camera":
        capture_path, capture_metadata = capture_from_camera(args, evidence_dir)

    model = validate_model_dir(args.model_dir, args.verify_hash)
    comparison = compare_images(args.standard, capture_path, evidence_dir)
    production_ready = bool(model["verified"] and comparison["overall_result"] in ("pass", "needs_fix", "reject"))
    report = {
        "schema_version": "jetson-photo-production-smoke-v1",
        "run_id": run_id,
        "created_at": now_iso(),
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "opencv": cv2.__version__,
        },
        "repo": {
            "path": os.getcwd(),
            "commit": git_commit(os.getcwd()),
        },
        "context": {
            "tenant_id": args.tenant_id,
            "sku_id": args.sku_id,
            "station_id": args.station_id,
            "inspection_id": args.inspection_id or run_id,
        },
        "runtime": {
            "engine": "jetson_cv_photo_simulation",
            "model_name": "Qwen3-VL-2B-Instruct-MNN assets verified; OpenCV visual comparator used",
            "local_qwen_mnn_inference": False,
            "note": "Current repo has no wired Jetson local MNN inference provider; this validates the production photo-input path and model assets.",
        },
        "deployment_scope": {
            "class": "test_hardware_photo_simulation",
            "production_eligible": False,
            "hardware_role": "Jetson Xavier NX test machine",
            "configuration": "simulated still photo input may replace CV module input",
            "not_production_reasons": [
                "APP_ENV=test style validation",
                "single test machine, not separated Pad/Server production roles",
                "local Qwen MNN VLM inference provider is not wired",
                "human final decision remains required",
            ],
        },
        "inputs": {
            "standard_photo": os.path.abspath(args.standard),
            "capture_photo": os.path.abspath(capture_path),
            "capture_metadata": capture_metadata,
        },
        "model_assets": model,
        "inspection": comparison,
        "production_ready_smoke": production_ready,
        "human_final_decision_required": True,
    }
    report_path = os.path.join(evidence_dir, "report.json")
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    report["report_path"] = report_path
    return report


def parse_args(argv):
    here = os.getcwd()
    default_std = os.path.join(here, "tests", "fixtures", "red_square.png")
    default_cap = os.path.join(here, "tests", "fixtures", "red_square_with_dot.png")
    parser = argparse.ArgumentParser(description="Run Jetson photo-input production smoke test.")
    parser.add_argument("--standard", default=default_std, help="standard/reference photo path")
    parser.add_argument("--capture", default=default_cap, help="captured/production photo path")
    parser.add_argument("--capture-source", choices=["file", "camera"], default="file", help="read capture from file or Jetson CV/camera module")
    parser.add_argument("--camera-backend", choices=["auto", "csi", "v4l2"], default="auto", help="camera backend for --capture-source camera")
    parser.add_argument("--camera-index", type=int, default=0, help="V4L2 camera index")
    parser.add_argument("--camera-sensor-id", type=int, default=0, help="CSI sensor-id for nvarguscamerasrc")
    parser.add_argument("--camera-width", type=int, default=1280)
    parser.add_argument("--camera-height", type=int, default=720)
    parser.add_argument("--camera-fps", type=int, default=30)
    parser.add_argument("--camera-flip-method", type=int, default=0)
    parser.add_argument("--camera-warmup-frames", type=int, default=5)
    parser.add_argument("--model-dir", default="/home/giraffe/work/qwen3-vl-2b-mnn", help="Qwen MNN model directory")
    parser.add_argument("--out-dir", default="/home/giraffe/work/giraffe-qc-model/artifacts/jetson_photo_smoke")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--sku-id", default="demo-sku")
    parser.add_argument("--station-id", default="jetson-nx")
    parser.add_argument("--inspection-id", default="")
    parser.add_argument("--verify-hash", action="store_true", help="sha256-check large MNN weight files")
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    try:
        report = build_report(args)
    except Exception as exc:
        error = {
            "schema_version": "jetson-photo-production-smoke-v1",
            "created_at": now_iso(),
            "overall_result": "review_required",
            "production_ready_smoke": False,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "human_final_decision_required": True,
        }
        print(json.dumps(error, indent=2, sort_keys=True))
        return 2
    print(json.dumps({
        "report_path": report["report_path"],
        "production_ready_smoke": report["production_ready_smoke"],
        "overall_result": report["inspection"]["overall_result"],
        "similarity_score": report["inspection"]["similarity_score"],
        "model_assets_verified": report["model_assets"]["verified"],
        "local_qwen_mnn_inference": report["runtime"]["local_qwen_mnn_inference"],
        "production_eligible": report["deployment_scope"]["production_eligible"],
        "deployment_class": report["deployment_scope"]["class"],
    }, indent=2, sort_keys=True))
    return 0 if report["production_ready_smoke"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
