#!/usr/bin/env python3
"""Phase 1 camera -> HTTP inference -> display harness (system Python 3.6)."""
from __future__ import print_function

import argparse
import base64
import hashlib
import hmac
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import cv2


def post_json(url, payload, timeout=30):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(url, data=raw, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.getcode(), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def signature(pair_key, payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(pair_key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def load_fixture(path):
    with open(path, "r") as handle:
        fixture = json.load(handle)
    required = {"standard_revision_id", "bundle_version", "detection_points"}
    missing = sorted(required.difference(fixture))
    if missing:
        raise ValueError("fixture missing: " + ",".join(missing))
    return fixture


def infer(base_url, pad_id, pair_key, frame, fixture):
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise RuntimeError("jpeg_encode_failed")
    payload = {
        "job_id": "phase1-" + uuid.uuid4().hex,
        "standard_revision_id": fixture["standard_revision_id"],
        "bundle_version": fixture["bundle_version"],
        "image": "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
        "detection_points": fixture["detection_points"],
    }
    envelope = {"pad_device_id": pad_id, "signature": signature(pair_key, payload), "request": payload}
    started = time.monotonic()
    status, response = post_json(base_url + "/infer", envelope, timeout=120)
    return status, response, (time.monotonic() - started) * 1000.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8600")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capture-once", action="store_true")
    args = parser.parse_args()
    fixture = load_fixture(args.fixture)
    pad_id = "phase1-local-cv"
    status, handshake = post_json(args.base_url + "/phase1/pair-loopback", {
        "pad_device_id": pad_id, "pad_pubkey": "phase1-local-only"
    })
    if status != 200:
        raise RuntimeError("pairing failed: %s %s" % (status, handshake))
    pair_key = handshake["pair_key"]
    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        raise RuntimeError("camera_open_failed")
    last_lines = ["SPACE=capture  Q=quit"]
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError("camera_read_failed")
            view = frame.copy()
            for index, line in enumerate(last_lines):
                cv2.putText(view, line, (10, 25 + index * 24), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (0, 255, 0), 1, cv2.LINE_AA)
            cv2.imshow("Giraffe QC Phase 1", view)
            key = cv2.waitKey(1) & 0xFF
            if args.capture_once or key == 32:
                status, response, latency_ms = infer(args.base_url, pad_id, pair_key, frame, fixture)
                if status != 200:
                    last_lines = ["HTTP %s: %s" % (status, response)]
                else:
                    last_lines = ["HTTP %.1f ms" % latency_ms]
                    last_lines.extend("%s: %s %.2f" % (r["point_code"], r["result"], r["confidence"])
                                      for r in response["per_point_results"])
                print(json.dumps({"http_status": status, "latency_ms": latency_ms, "response": response},
                                 sort_keys=True))
                if args.capture_once:
                    break
            if key in (ord("q"), 27):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
