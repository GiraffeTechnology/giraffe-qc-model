"""Bounded external-drive write/fsync/read-back probe; this is not a benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


BLOCK = bytes(range(256)) * 4096


def run_probe(root: Path, size_mib: int) -> dict[str, object]:
    if size_mib < 1 or size_mib > 256:
        raise ValueError("probe size must be between 1 and 256 MiB")
    root = root.resolve()
    root.relative_to(Path("/Volumes"))
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    probe = evidence / f"rw-probe-{size_mib}MiB.bin"
    target_size = size_mib * 1024 * 1024
    write_hash = hashlib.sha256()
    write_started = time.perf_counter()
    with probe.open("wb") as destination:
        remaining = target_size
        while remaining:
            chunk = BLOCK[: min(len(BLOCK), remaining)]
            destination.write(chunk)
            write_hash.update(chunk)
            remaining -= len(chunk)
        destination.flush()
        os.fsync(destination.fileno())
    write_elapsed = time.perf_counter() - write_started

    read_hash = hashlib.sha256()
    read_started = time.perf_counter()
    with probe.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            read_hash.update(chunk)
    read_elapsed = time.perf_counter() - read_started
    result = {
        "schema_version": "stage2-drive-probe-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "volume_name": root.parts[2],
        "stage2_root": root.name,
        "probe_file": str(probe.relative_to(root)),
        "probe_size_bytes": target_size,
        "bytes_on_disk": probe.stat().st_size,
        "write_fsync_completed": True,
        "read_back_completed": True,
        "sha256": write_hash.hexdigest(),
        "sha256_matches": write_hash.digest() == read_hash.digest(),
        "write_elapsed_seconds": round(write_elapsed, 6),
        "read_elapsed_seconds": round(read_elapsed, 6),
        "performance_claim": False,
        "timing_note": (
            "Bounded sandbox observation only; cache state is uncontrolled and these "
            "timings are not device throughput or production-performance evidence."
        ),
    }
    (evidence / "drive-probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--size-mib", type=int, default=64)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = run_probe(Path(args.root), args.size_mib)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        "external-drive bounded probe complete; "
        f"sha256_matches={str(result['sha256_matches']).lower()} performance_claim=false"
    )
    return 0 if result["sha256_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
