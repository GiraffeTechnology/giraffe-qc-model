#!/usr/bin/env python3
"""Verify a pinned MNN SDK lockfile (GAP-03) — run before building the bridge.

Refuses (exit 1) when the lockfile:

* is missing any required field;
* still holds a template placeholder (any value starting with ``<REPLACE``)
  or the literal string ``latest``;
* has ``approved`` set to anything other than ``true``;
* (when ``--archive`` is given) the archive's SHA-256 does not match the
  lockfile's ``sha256`` field.

This is a pure gate — it never downloads, builds, or fabricates a passing
result. A clean run only means "the lock is internally consistent and
approved," not that the SDK has been hardware-validated
(see jetson_runner/HARDWARE_VALIDATION.md for that separate gate).

Usage:
    python3 scripts/jetson_verify_mnn_lock.py \
        --lockfile deploy/jetson/mnn-sdk.lock.json \
        [--archive /path/to/fetched-mnn-sdk.tar.gz]

Stdlib-only; compatible with JetPack 5.x Python 3.8.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys

_REQUIRED_FIELDS = (
    "source_url",
    "git_commit",
    "sha256",
    "build_flags",
    "target_arch",
    "jetpack_version",
    "l4t_version",
)


def _is_placeholder(value) -> bool:
    if isinstance(value, str):
        return value.startswith("<REPLACE") or value.strip().lower() == "latest"
    if isinstance(value, list):
        return not value or any(_is_placeholder(v) for v in value)
    return False


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(lock: dict, archive_path: str | None) -> list[str]:
    problems: list[str] = []

    if lock.get("approved") is not True:
        problems.append(f"approved is {lock.get('approved')!r}, must be exactly true")

    for field in _REQUIRED_FIELDS:
        if field not in lock:
            problems.append(f"missing required field: {field}")
            continue
        if _is_placeholder(lock[field]):
            problems.append(f"field {field!r} still holds a placeholder/unpinned value: {lock[field]!r}")

    digest = lock.get("sha256", "")
    if isinstance(digest, str) and digest and not _is_placeholder(digest):
        if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest.lower()):
            problems.append(f"sha256 is not a 64-hex-char digest: {digest!r}")

    if archive_path:
        try:
            actual = _sha256_file(archive_path)
        except OSError as exc:
            problems.append(f"cannot read --archive {archive_path}: {exc}")
        else:
            expected = lock.get("sha256", "")
            if actual != expected:
                problems.append(
                    f"archive sha256 mismatch: expected {expected!r}, got {actual!r} "
                    f"for {archive_path} — refusing (fail closed)"
                )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lockfile", default="deploy/jetson/mnn-sdk.lock.json")
    parser.add_argument("--archive", default=None, help="path to a fetched SDK archive to verify against sha256")
    args = parser.parse_args()

    try:
        with open(args.lockfile, "r") as fh:
            lock = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.lockfile}: {exc}", file=sys.stderr)
        return 2

    problems = verify(lock, args.archive)
    if problems:
        print("MNN SDK lock verification FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"MNN SDK lock verification passed: {args.lockfile} is approved and internally consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
