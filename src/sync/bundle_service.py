"""Standard Bundle build + verification (Task 03).

Archive format: **tar.gz** (documented in docs/offline-sync.md). Members:
  - ``manifest.json``   : bundle + SKU/standard metadata (canonical UTF-8 JSON).
  - ``checksum.sha256`` : ``<hex>␠␠<path>`` per line for manifest.json + every photo.
  - ``bundle.sig``      : base64 Ed25519 signature over manifest_bytes + b"\\n" +
                          checksum_bytes (see bundle_signing).
  - ``photos/<sku_id>/<filename>`` : standard photo files.

Only ACTIVE standard revisions are exported. Bundles are idempotent to import and
carry a monotonic ``bundle_version`` per (tenant, line_scope) for downgrade
protection.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.execution_models import QCInspectionJob  # noqa: F401 (ensures model registry)
from src.db.qc_bundle_models import QCStandardBundle
from src.db.sku_models import (
    QCDetectionPoint,
    QCInspectionRequirement,
    QCSkuItem,
    QCSkuStandardRevision,
    QCStandardPhoto,
)
from src.sync import bundle_signing

BUNDLE_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
CHECKSUM_NAME = "checksum.sha256"
SIGNATURE_NAME = "bundle.sig"


class BundleExportError(RuntimeError):
    """Raised when a bundle cannot be built (e.g. missing photo file)."""


class BundleVerifyError(RuntimeError):
    """Raised when a bundle fails signature / checksum / manifest verification."""


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bundle_store_dir() -> Path:
    return Path(os.getenv("QC_BUNDLE_STORE_DIR", "./data/bundles"))


def _canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _signed_payload(manifest_bytes: bytes, checksum_bytes: bytes) -> bytes:
    return manifest_bytes + b"\n" + checksum_bytes


# ── Manifest assembly ─────────────────────────────────────────────────────────


def _photo_filename(photo: QCStandardPhoto) -> str:
    """Deterministic archive filename for a photo."""
    if photo.local_path:
        base = os.path.basename(photo.local_path)
        if base:
            return base
    ext = "jpg"
    if photo.mime_type and "/" in photo.mime_type:
        ext = photo.mime_type.split("/", 1)[1] or "jpg"
    return f"{photo.id}.{ext}"


@dataclass
class _BuiltManifest:
    manifest: dict
    # sku_id -> list of (archive_relpath, source_path)
    photo_files: list[tuple[str, str]]


def _build_manifest(
    db: Session, tenant_id: str, bundle_version: int, fingerprint: str,
    line_scope: str, sku_filter: Optional[list[str]],
) -> _BuiltManifest:
    q = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.tenant_id == tenant_id)
        .order_by(QCSkuItem.item_number)
    )
    if sku_filter:
        q = q.filter(QCSkuItem.id.in_(sku_filter))

    skus_out: list[dict] = []
    photo_files: list[tuple[str, str]] = []
    missing_photos: list[str] = []

    for sku in q.all():
        active = (
            db.query(QCSkuStandardRevision)
            .filter(
                QCSkuStandardRevision.sku_id == sku.id,
                QCSkuStandardRevision.tenant_id == tenant_id,
                QCSkuStandardRevision.status == "active",
            )
            .order_by(QCSkuStandardRevision.revision_no.desc())
            .first()
        )
        if active is None:
            # No confirmed/active standard → never ships (no-guess).
            continue

        points = (
            db.query(QCDetectionPoint)
            .filter(
                QCDetectionPoint.standard_revision_id == active.id,
                QCDetectionPoint.is_active.is_(True),
            )
            .order_by(QCDetectionPoint.sort_order, QCDetectionPoint.point_code)
            .all()
        )
        reqs = (
            db.query(QCInspectionRequirement)
            .filter(
                QCInspectionRequirement.standard_revision_id == active.id,
                QCInspectionRequirement.is_active.is_(True),
            )
            .order_by(QCInspectionRequirement.sort_order, QCInspectionRequirement.code)
            .all()
        )
        photos = (
            db.query(QCStandardPhoto)
            .filter(QCStandardPhoto.standard_revision_id == active.id)
            .order_by(QCStandardPhoto.is_primary.desc(), QCStandardPhoto.id)
            .all()
        )

        photos_out: list[dict] = []
        for photo in photos:
            filename = _photo_filename(photo)
            relpath = f"photos/{sku.id}/{filename}"
            src = photo.local_path
            if not src or not os.path.isfile(src):
                missing_photos.append(f"{sku.item_number}:{photo.id} ({src})")
                continue
            photo_files.append((relpath, src))
            photos_out.append({
                "id": photo.id,
                "filename": filename,
                "path": relpath,
                "angle": photo.angle,
                "view_type": photo.view_type,
                "is_primary": photo.is_primary,
                "sha256": photo.sha256,
                "width_px": photo.width_px,
                "height_px": photo.height_px,
                "mime_type": photo.mime_type,
            })

        skus_out.append({
            "sku_id": sku.id,
            "item_number": sku.item_number,
            "name": sku.name,
            "category": sku.category,
            "active_standard_revision_id": active.id,
            "revision_no": active.revision_no,
            "detection_points": [{
                "id": p.id,
                "point_code": p.point_code,
                "label": p.label,
                "description": p.description,
                "roi_json": p.roi_json,
                "expected_value": p.expected_value,
                "method_hint": p.method_hint,
                "severity": p.severity,
                "sort_order": p.sort_order,
            } for p in points],
            "inspection_requirements": [{
                "id": r.id,
                "code": r.code,
                "title": r.title,
                "requirement_text": r.requirement_text,
                "severity": r.severity,
                "pass_criteria": r.pass_criteria,
                "tolerance_json": r.tolerance_json,
                "sort_order": r.sort_order,
            } for r in reqs],
            "photos": photos_out,
        })

    if missing_photos:
        raise BundleExportError(
            "Standard photo file(s) missing on disk; refusing to export a partial "
            f"bundle: {missing_photos}"
        )

    manifest = {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "bundle_version": bundle_version,
        "generated_at": _now().isoformat(),
        "tenant_id": tenant_id,
        "line_scope": line_scope,
        "signing_key_fingerprint": fingerprint,
        "sku_count": len(skus_out),
        "skus": skus_out,
    }
    return _BuiltManifest(manifest=manifest, photo_files=photo_files)


# ── Public API ────────────────────────────────────────────────────────────────


@dataclass
class ExportedBundle:
    record: QCStandardBundle
    archive_path: Path
    manifest: dict


def next_bundle_version(db: Session, tenant_id: str, line_scope: str) -> int:
    current = (
        db.query(func.max(QCStandardBundle.bundle_version))
        .filter(
            QCStandardBundle.tenant_id == tenant_id,
            QCStandardBundle.line_scope == line_scope,
        )
        .scalar()
    )
    return (current or 0) + 1


def export_bundle(
    db: Session,
    tenant_id: str,
    line_scope: str = "",
    sku_filter: Optional[list[str]] = None,
    generated_by: Optional[str] = None,
    signer: Optional[bundle_signing.BundleSigner] = None,
) -> ExportedBundle:
    """Build, sign, persist, and store a standard bundle. Fail-closed on any
    missing photo file. Returns the persisted record + archive path + manifest."""
    signer = signer or bundle_signing.load_signer()
    version = next_bundle_version(db, tenant_id, line_scope)

    built = _build_manifest(db, tenant_id, version, signer.fingerprint, line_scope, sku_filter)
    manifest_bytes = _canonical_json(built.manifest)

    # checksum.sha256 over manifest.json + every photo file.
    checksum_lines = [f"{_sha256_bytes(manifest_bytes)}  {MANIFEST_NAME}"]
    photo_bytes: dict[str, bytes] = {}
    for relpath, src in built.photo_files:
        with open(src, "rb") as fh:
            data = fh.read()
        photo_bytes[relpath] = data
        checksum_lines.append(f"{_sha256_bytes(data)}  {relpath}")
    checksum_bytes = ("\n".join(checksum_lines) + "\n").encode("utf-8")

    signature_b64 = signer.sign(_signed_payload(manifest_bytes, checksum_bytes))

    # Assemble the tar.gz archive in memory.
    archive_buf = io.BytesIO()
    with tarfile.open(fileobj=archive_buf, mode="w:gz") as tar:
        _add_bytes(tar, MANIFEST_NAME, manifest_bytes)
        _add_bytes(tar, CHECKSUM_NAME, checksum_bytes)
        _add_bytes(tar, SIGNATURE_NAME, signature_b64.encode("ascii"))
        for relpath, data in photo_bytes.items():
            _add_bytes(tar, relpath, data)
    archive_data = archive_buf.getvalue()

    store = _bundle_store_dir()
    store.mkdir(parents=True, exist_ok=True)
    safe_line = line_scope or "all"
    archive_filename = f"{tenant_id}_{safe_line}_v{version}.tar.gz"
    archive_path = store / archive_filename
    archive_path.write_bytes(archive_data)

    record = QCStandardBundle(
        id=_uid(),
        tenant_id=tenant_id,
        line_scope=line_scope,
        bundle_version=version,
        bundle_format_version=BUNDLE_FORMAT_VERSION,
        sku_count=built.manifest["sku_count"],
        archive_sha256=_sha256_bytes(archive_data),
        manifest_sha256=_sha256_bytes(manifest_bytes),
        signature_b64=signature_b64,
        signing_key_fingerprint=signer.fingerprint,
        archive_filename=archive_filename,
        generated_by=generated_by,
        generated_at=_now(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return ExportedBundle(record=record, archive_path=archive_path, manifest=built.manifest)


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))


def latest_bundle(db: Session, tenant_id: str, line_scope: str = "") -> Optional[QCStandardBundle]:
    return (
        db.query(QCStandardBundle)
        .filter(
            QCStandardBundle.tenant_id == tenant_id,
            QCStandardBundle.line_scope == line_scope,
        )
        .order_by(QCStandardBundle.bundle_version.desc())
        .first()
    )


def verify_bundle_archive(archive_bytes: bytes, public_key) -> dict:
    """Verify a bundle the way the Pad importer does, then return the manifest.

    Order: signature over (manifest + checksum) FIRST, then per-file checksums,
    then manifest parse. Raises BundleVerifyError on any failure. This mirrors the
    Android importer and backs the server-side tamper test.
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
            members = {m.name: m for m in tar.getmembers()}
            for required in (MANIFEST_NAME, CHECKSUM_NAME, SIGNATURE_NAME):
                if required not in members:
                    raise BundleVerifyError(f"bundle missing {required}")
            manifest_bytes = tar.extractfile(members[MANIFEST_NAME]).read()
            checksum_bytes = tar.extractfile(members[CHECKSUM_NAME]).read()
            signature_b64 = tar.extractfile(members[SIGNATURE_NAME]).read().decode("ascii").strip()

            # 1) signature over manifest + checksum
            if not bundle_signing.verify(
                public_key, _signed_payload(manifest_bytes, checksum_bytes), signature_b64
            ):
                raise BundleVerifyError("signature verification failed")

            # 2) per-file checksums
            expected: dict[str, str] = {}
            for line in checksum_bytes.decode("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    raise BundleVerifyError(f"malformed checksum line: {line!r}")
                expected[parts[1].lstrip("*")] = parts[0].lower()

            if _sha256_bytes(manifest_bytes) != expected.get(MANIFEST_NAME):
                raise BundleVerifyError("manifest checksum mismatch")
            for name, member in members.items():
                if name in (MANIFEST_NAME, CHECKSUM_NAME, SIGNATURE_NAME):
                    continue
                data = tar.extractfile(member).read()
                if name not in expected:
                    raise BundleVerifyError(f"file not listed in checksum manifest: {name}")
                if _sha256_bytes(data) != expected[name]:
                    raise BundleVerifyError(f"checksum mismatch for {name}")
    except tarfile.TarError as exc:
        raise BundleVerifyError(f"corrupt archive: {exc}") from exc

    # 3) manifest parse (only after integrity is proven)
    try:
        return json.loads(manifest_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BundleVerifyError(f"manifest not valid JSON: {exc}") from exc
