"""Local storage utilities for the Giraffe QC Model.

All paths are resolved at call time from env QC_STORAGE_ROOT
(default: ./data/giraffe_qc).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple


def _storage_root() -> Path:
    """Returns the storage root, read at call time so tests can monkeypatch."""
    return Path(os.getenv("QC_STORAGE_ROOT", "./data/giraffe_qc"))


def get_standard_photo_dir(tenant_id: str, sku_id: str, version: str) -> Path:
    """Returns the directory for storing standard photos.

    Path: {root}/GiraffeQC/standards/{tenant}/{sku}/{version}/photos/
    """
    return _storage_root() / "GiraffeQC" / "standards" / tenant_id / sku_id / version / "photos"


def get_capture_dir(tenant_id: str, sku_id: str, date_str: str) -> Path:
    """Returns the directory for storing capture photos.

    Path: {root}/GiraffeQC/captures/{tenant}/{sku}/{date}/
    """
    return _storage_root() / "GiraffeQC" / "captures" / tenant_id / sku_id / date_str


def get_inspection_dir(tenant_id: str, sku_id: str, inspection_id: str) -> Path:
    """Returns the directory for storing inspection artifacts.

    Path: {root}/GiraffeQC/inspections/{tenant}/{sku}/{inspection_id}/
    """
    return _storage_root() / "GiraffeQC" / "inspections" / tenant_id / sku_id / inspection_id


def _compute_sha256(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def save_standard_photo(
    source_path: str,
    standard_id: str,
    sku_id: str,
    tenant_id: str,
    version: str,
    angle: str,
) -> Tuple[Path, str]:
    """Save a standard photo with a unique deterministic filename.

    Filename format: {sku_id}_{version}_{angle}_{uuid}.{ext}
    Returns (dest_path, sha256)
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Source image not found: {source_path}")

    dest_dir = get_standard_photo_dir(tenant_id, sku_id, version)
    dest_dir.mkdir(parents=True, exist_ok=True)

    ext = src.suffix.lower() or ".jpg"
    unique_id = uuid.uuid4().hex
    filename = f"{sku_id}_{version}_{angle}_{unique_id}{ext}"
    dest_path = dest_dir / filename

    shutil.copy2(str(src), str(dest_path))
    sha256 = _compute_sha256(dest_path)
    return dest_path, sha256


def save_capture_photo(
    source_path: str,
    inspection_id: str,
    tenant_id: str,
    sku_id: str,
) -> Tuple[Path, str]:
    """Save a capture photo with a unique filename and write a sidecar JSON.

    Filename format: CAP_{inspection_id}_{utc_ts}_{uuid}.jpg
    Sidecar JSON: same path with .json suffix.
    Returns (dest_path, sha256)
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Source capture image not found: {source_path}")

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    dest_dir = get_capture_dir(tenant_id, sku_id, date_str)
    dest_dir.mkdir(parents=True, exist_ok=True)

    utc_ts = now.strftime("%Y%m%dT%H%M%SZ")
    unique_id = uuid.uuid4().hex
    filename = f"CAP_{inspection_id}_{utc_ts}_{unique_id}.jpg"
    dest_path = dest_dir / filename

    shutil.copy2(str(src), str(dest_path))
    sha256 = _compute_sha256(dest_path)

    # Write sidecar JSON
    sidecar = {
        "inspection_id": inspection_id,
        "tenant_id": tenant_id,
        "sku_id": sku_id,
        "captured_at": now.isoformat(),
        "sha256": sha256,
        "original_filename": src.name,
    }
    sidecar_path = dest_path.with_suffix(".json")
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2)

    return dest_path, sha256
