#!/usr/bin/env python3
"""Repeat a fixed camera frame through the Phase 1 HTTP contract."""
from __future__ import print_function

import argparse
import csv
import json
import math
import os
import time

import cv2

from jetson_phase1_cv import infer, load_fixture, post_json


def percentile(values, fraction):
    ordered = sorted(values)
    index = int(math.ceil(fraction * len(ordered))) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def read_text(path, default=""):
    try:
        with open(path, "r") as handle:
            return handle.read().strip()
    except (IOError, OSError):
        return default


def system_metrics():
    temperatures = []
    for index in range(32):
        raw = read_text("/sys/class/thermal/thermal_zone%d/temp" % index)
        if raw:
            try:
                temperatures.append(float(raw) / 1000.0)
            except ValueError:
                pass
    memory_kb = 0
    for line in read_text("/proc/meminfo").splitlines():
        if line.startswith("MemAvailable:"):
            memory_kb = int(line.split()[1])
            break
    gpu_raw = read_text("/sys/devices/gpu.0/load", "0")
    try:
        gpu_percent = float(gpu_raw) / 10.0
    except ValueError:
        gpu_percent = 0.0
    runner_rss_kb = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        command = read_text("/proc/%s/cmdline" % pid).replace("\x00", " ")
        if "jetson_runner.app.main" not in command:
            continue
        for line in read_text("/proc/%s/status" % pid).splitlines():
            if line.startswith("VmRSS:"):
                runner_rss_kb += int(line.split()[1])
                break
    return {
        "max_temp_c": "%.3f" % max(temperatures) if temperatures else "",
        "gpu_load_percent": "%.1f" % gpu_percent,
        "mem_available_kb": memory_kb,
        "runner_rss_kb": runner_rss_kb,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8600")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--duration-seconds", type=float, default=0)
    parser.add_argument("--interval-seconds", type=float, default=0)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()

    fixture = load_fixture(args.fixture)
    pad_id = "phase1-benchmark"
    status, handshake = post_json(args.base_url + "/phase1/pair-loopback", {
        "pad_device_id": pad_id, "pad_pubkey": "phase1-benchmark-local"
    })
    if status != 200:
        raise RuntimeError("pairing failed: %s %s" % (status, handshake))

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        raise RuntimeError("camera_open_failed")
    ok, fixed_frame = camera.read()
    camera.release()
    if not ok:
        raise RuntimeError("camera_read_failed")

    started = time.monotonic()
    rows = []
    request_number = 0
    csv_handle = open(args.csv, "w")
    writer = None
    while True:
        request_number += 1
        status, response, latency_ms = infer(
            args.base_url, pad_id, handshake["pair_key"], fixed_frame, fixture
        )
        now = time.monotonic()
        row = {
            "request": request_number,
            "elapsed_seconds": "%.6f" % (now - started),
            "latency_ms": "%.6f" % latency_ms,
            "http_status": status,
            "result_count": len(response.get("per_point_results", [])),
        }
        row.update(system_metrics())
        rows.append(row)
        if writer is None:
            writer = csv.DictWriter(csv_handle, fieldnames=list(row.keys()))
            writer.writeheader()
        writer.writerow(row)
        csv_handle.flush()
        os.fsync(csv_handle.fileno())
        if status != 200:
            raise RuntimeError("request failed: %s %s" % (status, response))
        if args.duration_seconds:
            if now - started >= args.duration_seconds:
                break
        elif request_number >= args.requests:
            break
        if args.interval_seconds:
            time.sleep(args.interval_seconds)
    csv_handle.close()
    latencies = [float(row["latency_ms"]) for row in rows]
    summary = {
        "runner_mode": "mock",
        "fixed_frame_shape": list(fixed_frame.shape),
        "requests": len(rows),
        "duration_seconds": time.monotonic() - started,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "max_ms": max(latencies),
        "failures": sum(1 for row in rows if row["http_status"] != 200),
    }
    with open(args.summary, "w") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
