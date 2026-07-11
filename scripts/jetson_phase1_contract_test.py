#!/usr/bin/env python3
"""Negative HTTP contract checks for the Phase 1 runner."""
from __future__ import print_function

import json

from jetson_phase1_cv import post_json, signature


def main():
    base = "http://127.0.0.1:8600"
    pad_id = "phase1-negative-tests"
    status, pairing = post_json(base + "/phase1/pair-loopback", {
        "pad_device_id": pad_id, "pad_pubkey": "negative-tests-local"
    })
    assert status == 200, (status, pairing)
    malformed = {
        "job_id": "bad-empty-points",
        "standard_revision_id": "phase1-rev",
        "bundle_version": "fixture-1",
        "image": "data:image/jpeg;base64,AA==",
        "detection_points": [],
    }
    status, body = post_json(base + "/infer", {
        "pad_device_id": pad_id,
        "signature": signature(pairing["pair_key"], malformed),
        "request": malformed,
    })
    print(json.dumps({"case": "empty_detection_points", "status": status, "body": body}, sort_keys=True))
    assert status == 403 and "invalid_request" in body.get("detail", "")
    status, body = post_json(base + "/infer", {
        "pad_device_id": pad_id, "signature": "tampered", "request": malformed
    })
    print(json.dumps({"case": "bad_signature", "status": status, "body": body}, sort_keys=True))
    assert status == 403 and body.get("detail") == "bad_signature"


if __name__ == "__main__":
    main()
