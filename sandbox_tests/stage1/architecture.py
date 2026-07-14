"""Stage 1 deployment checks for the sandbox checkout, data root, and MySQL."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


RUNTIME_ENV_KEYS = {
    "QC_DB_URL",
    "SAMPLE_STORE_DIR",
    "CAPTURE_DIR",
    "STAGE1_DATA_ROOT",
}
REQUIRED_TABLES = {"inspection_runs", "qc_points", "qc_results"}


class ArchitectureVerificationError(RuntimeError):
    """A redacted Stage 1 architecture-gate failure."""


def load_runtime_env_file(path: str | Path) -> None:
    """Load the secret runtime env without printing values or accepting extras."""
    source = Path(path)
    if not source.is_file():
        raise ArchitectureVerificationError("runtime_env_missing")
    if stat.S_IMODE(source.stat().st_mode) & 0o077:
        raise ArchitectureVerificationError("runtime_env_permissions_must_be_0600")
    for line_number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ArchitectureVerificationError(f"runtime_env_invalid_line_{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in RUNTIME_ENV_KEYS:
            raise ArchitectureVerificationError(f"runtime_env_key_refused_{line_number}")
        value = value.strip().strip('"').strip("'")
        if not value:
            raise ArchitectureVerificationError(f"runtime_env_value_missing_{line_number}")
        os.environ.setdefault(key, value)


def verify_architecture(repository_root: str | Path) -> dict[str, object]:
    """Return endpoint-free evidence for the Stage 1 deployment architecture."""
    root = Path(repository_root).resolve()
    data_root = Path(os.getenv("STAGE1_DATA_ROOT", "")).expanduser().resolve()
    sample_root = Path(os.getenv("SAMPLE_STORE_DIR", "")).expanduser().resolve()
    capture_root = Path(os.getenv("CAPTURE_DIR", "")).expanduser().resolve()
    db_url = os.getenv("QC_DB_URL", "").strip()
    if not db_url:
        raise ArchitectureVerificationError("database_url_missing")
    if root not in data_root.parents or data_root.name != "data":
        raise ArchitectureVerificationError("data_root_must_be_repository_data_directory")
    if data_root not in sample_root.parents or data_root not in capture_root.parents:
        raise ArchitectureVerificationError("runtime_data_paths_must_be_below_data_root")
    for directory in (data_root, sample_root, capture_root):
        directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    probe = data_root / ".stage1-write-probe"
    probe_created = False
    try:
        descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        probe_created = True
        os.write(descriptor, b"stage1")
        os.close(descriptor)
    except OSError as exc:
        raise ArchitectureVerificationError("data_root_write_check_failed") from exc
    finally:
        if probe_created:
            probe.unlink(missing_ok=True)

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        if engine.dialect.name != "mysql":
            raise ArchitectureVerificationError("database_dialect_must_be_mysql")
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        tables = set(inspect(engine).get_table_names())
        engine.dispose()
    except ArchitectureVerificationError:
        raise
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise ArchitectureVerificationError("database_connectivity_or_schema_check_failed") from exc
    missing = REQUIRED_TABLES - tables
    if missing:
        raise ArchitectureVerificationError("database_schema_incomplete")

    return {
        "ready": True,
        "source_checkout_present": (root / ".git").is_dir(),
        "data_root": "data",
        "data_root_within_checkout": True,
        "data_root_writable": True,
        "sample_and_capture_paths_within_data_root": True,
        "database_provider": "CTYUN MySQL",
        "database_dialect": "mysql",
        "database_reachable": True,
        "database_schema_initialized": True,
        "database_table_count": len(tables),
        "database_endpoint_redacted": True,
    }


def architecture_ready(evidence: dict[str, object] | None) -> bool:
    if not evidence or evidence.get("ready") is not True:
        return False
    required = (
        "source_checkout_present",
        "data_root_within_checkout",
        "data_root_writable",
        "sample_and_capture_paths_within_data_root",
        "database_reachable",
        "database_schema_initialized",
        "database_endpoint_redacted",
    )
    return all(evidence.get(key) is True for key in required)
