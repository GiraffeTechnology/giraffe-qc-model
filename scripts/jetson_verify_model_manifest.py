#!/usr/bin/env python3
"""Verify a Group A model manifest against the files on disk (GAP-04).

Refuses (exit 1) when:

* any required field is missing or still holds a template placeholder;
* ``approved`` is not exactly ``true``;
* a declared file is missing, or its SHA-256/size does not match the
  manifest (fails closed — a mismatched export is never "close enough");
* ``target_mnn_sdk_commit`` does not match the paired
  ``deploy/jetson/mnn-sdk.lock.json`` (when that lock is itself approved) —
  a model exported against a different MNN SDK is not this deployment's
  approved pairing.

Missing model, mismatched digest, or failed load must produce
``not_ready`` / ``review_required`` at the service level — this script never
substitutes mock output or another model when verification fails.

Usage:
    python3 scripts/jetson_verify_model_manifest.py \
        --manifest /opt/giraffe/models/qwen3-vl-4b-mnn/model_manifest.json \
        [--mnn-lock deploy/jetson/mnn-sdk.lock.json]

Stdlib-only; compatible with JetPack 5.x Python 3.8.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

_REQUIRED_FIELDS = (
    "model_name",
    "model_alias",
    "upstream_revision",
    "mnn_export_tool",
    "mnn_export_tool_version",
    "quantization",
    "files",
    "min_memory_mb",
    "target_jetpack_version",
    "target_l4t_version",
    "target_mnn_sdk_commit",
    "license",
    "source",
)


def _is_placeholder(value) -> bool:
    if isinstance(value, str):
        return value.startswith("<REPLACE") or value.strip().lower() == "latest"
    if isinstance(value, list):
        return any(_is_placeholder(v) for v in value)
    return False


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(manifest: dict, model_dir: str, mnn_lock: dict | None) -> list[str]:
    problems: list[str] = []

    if manifest.get("approved") is not True:
        problems.append(f"approved is {manifest.get('approved')!r}, must be exactly true")

    for field in _REQUIRED_FIELDS:
        if field not in manifest:
            problems.append(f"missing required field: {field}")
            continue
        if field != "files" and _is_placeholder(manifest[field]):
            problems.append(f"field {field!r} still holds a placeholder value: {manifest[field]!r}")

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        problems.append("'files' must be a non-empty list")
        files = []

    for entry in files:
        if not isinstance(entry, dict):
            problems.append(f"file entry is not an object: {entry!r}")
            continue
        rel_path, expected_sha, expected_size = (
            entry.get("path"), entry.get("sha256"), entry.get("size_bytes"),
        )
        if _is_placeholder(rel_path) or _is_placeholder(expected_sha) or _is_placeholder(expected_size):
            problems.append(f"file entry still holds a placeholder value: {entry!r}")
            continue
        full_path = os.path.join(model_dir, rel_path)
        if not os.path.isfile(full_path):
            problems.append(f"declared file missing on disk: {rel_path}")
            continue
        actual_size = os.path.getsize(full_path)
        if actual_size != expected_size:
            problems.append(
                f"{rel_path}: size mismatch — manifest says {expected_size}, "
                f"actual is {actual_size}"
            )
        actual_sha = _sha256_file(full_path)
        if actual_sha != expected_sha:
            problems.append(
                f"{rel_path}: sha256 mismatch — manifest says {expected_sha!r}, "
                f"actual is {actual_sha!r} (fail closed: mismatched export refused)"
            )

    if mnn_lock is not None and mnn_lock.get("approved") is True:
        lock_commit = mnn_lock.get("git_commit")
        manifest_commit = manifest.get("target_mnn_sdk_commit")
        if lock_commit and manifest_commit and lock_commit != manifest_commit:
            problems.append(
                f"target_mnn_sdk_commit {manifest_commit!r} does not match the "
                f"approved MNN SDK lock's git_commit {lock_commit!r} — this model "
                "was not exported against the pinned SDK"
            )
        lock_jetpack = mnn_lock.get("jetpack_version")
        manifest_jetpack = manifest.get("target_jetpack_version")
        if lock_jetpack and manifest_jetpack and lock_jetpack != manifest_jetpack:
            problems.append(
                f"target_jetpack_version {manifest_jetpack!r} does not match the "
                f"approved MNN SDK lock's jetpack_version {lock_jetpack!r}"
            )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--mnn-lock", default=None,
        help="optional deploy/jetson/mnn-sdk.lock.json to cross-check the pairing against",
    )
    args = parser.parse_args()

    try:
        with open(args.manifest, "r") as fh:
            manifest = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.manifest}: {exc}", file=sys.stderr)
        return 2

    mnn_lock = None
    if args.mnn_lock:
        try:
            with open(args.mnn_lock, "r") as fh:
                mnn_lock = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: cannot read {args.mnn_lock}: {exc}", file=sys.stderr)
            return 2

    model_dir = os.path.dirname(os.path.abspath(args.manifest))
    problems = verify(manifest, model_dir, mnn_lock)
    if problems:
        print("Model manifest verification FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"Model manifest verification passed: {args.manifest} matches files on disk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
