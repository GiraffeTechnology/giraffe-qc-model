"""Refuse a tracked diff/report that contains the local sandbox server address."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from sandbox_tests.common import SandboxConfig, forbidden_server_values, load_env_file


def tracked_files(root: Path) -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    return [root / line for line in output.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default="sandbox.env")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    load_env_file(args.env_file)
    config = SandboxConfig.from_environment()
    root = Path(args.root).resolve()
    forbidden = {value.encode() for value in forbidden_server_values(config.server)}
    offenders = []
    for path in tracked_files(root):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(value and value in data for value in forbidden):
            offenders.append(str(path.relative_to(root)))
    if offenders:
        print("sandbox server address leak check FAILED in: " + ", ".join(offenders))
        return 1
    print("sandbox server address leak check passed; forbidden value remained redacted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
