"""Task 03 — offline standard sync: bundle export/signing + reverse-sync ingest.

Covers acceptance items 1, 2 (tamper), and the server half of 5/7:
  - export a bundle for a tenant with >=2 trained SKUs (manifest/checksum/signature)
  - signature + checksum verification; tampered manifest/photo rejected
  - only ACTIVE revisions ship; missing photo file fails closed
  - downgrade protection via monotonic bundle_version + /latest
  - idempotent reverse-sync ingest (dedupe on re-upload; unknown sku/point rejected)
  - API endpoints via TestClient (export, latest, download, public-key, batch)
"""
from __future__ import annotations

import io
import os
import tarfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.execution_models  # noqa: F401
import src.db.qc_bundle_models  # noqa: F401
from src.db.sku_models import (
    QCDetectionPoint,
    QCInspectionRequirement,
    QCSkuItem,
    QCSkuStandardRevision,
    QCStandardPhoto,
)
from src.sync import bundle_service, bundle_signing, result_ingest


# ── Signing key (test) ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def signing_key_env():
    priv_pem, pub_pem = bundle_signing.generate_keypair_pem()
    os.environ["QC_BUNDLE_SIGNING_KEY_PEM"] = priv_pem.decode("ascii")
    os.environ.pop("QC_BUNDLE_SIGNING_KEY", None)
    os.environ.pop("QC_BUNDLE_PUBLIC_KEY", None)
    os.environ.pop("QC_BUNDLE_PUBLIC_KEY_PEM", None)
    yield
    os.environ.pop("QC_BUNDLE_SIGNING_KEY_PEM", None)


@pytest.fixture()
def bundle_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_BUNDLE_STORE_DIR", str(tmp_path / "bundles"))
    return tmp_path


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    s = Session()
    yield s
    s.close()
    engine.dispose()


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_photo_file(tmp_path, name: str) -> str:
    p = tmp_path / name
    p.write_bytes(b"\xff\xd8\xff" + name.encode() + b"-fake-jpeg-bytes")
    return str(p)


def _seed_sku(
    db, tmp_path, tenant, sku_id, item_number, name, *,
    active=True, n_points=2, with_photo=True, photo_missing=False,
):
    db.add(QCSkuItem(id=sku_id, tenant_id=tenant, item_number=item_number, name=name, status="active"))
    rev_id = f"{sku_id}-rev1"
    db.add(QCSkuStandardRevision(
        id=rev_id, sku_id=sku_id, tenant_id=tenant, revision_no=1,
        status="active" if active else "draft",
    ))
    for i in range(n_points):
        db.add(QCDetectionPoint(
            id=f"{sku_id}-dp{i}", tenant_id=tenant, sku_id=sku_id, standard_revision_id=rev_id,
            point_code=f"P{i}", label=f"Point {i}", severity="major", sort_order=i, is_active=True,
        ))
    db.add(QCInspectionRequirement(
        id=f"{sku_id}-req0", tenant_id=tenant, sku_id=sku_id, standard_revision_id=rev_id,
        code="R0", title="Req 0", requirement_text="must match", severity="major", is_active=True,
    ))
    if with_photo:
        local = str(tmp_path / f"missing_{sku_id}.jpg") if photo_missing else _make_photo_file(tmp_path, f"{sku_id}.jpg")
        db.add(QCStandardPhoto(
            id=f"{sku_id}-ph0", tenant_id=tenant, sku_id=sku_id, standard_revision_id=rev_id,
            local_path=local, angle="front", is_primary=True, mime_type="image/jpeg",
        ))
    db.commit()
    return rev_id


# ── Tests: export / manifest / signature ───────────────────────────────────────


def test_export_two_skus_manifest_checksum_signature(db_session, tmp_path, bundle_store):
    _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "Widget A")
    _seed_sku(db_session, tmp_path, "default", "sku-b", "ITEM-B", "Widget B")

    exported = bundle_service.export_bundle(db_session, tenant_id="default", generated_by="qa")
    assert exported.record.bundle_version == 1
    assert exported.record.sku_count == 2
    assert exported.manifest["sku_count"] == 2

    archive = exported.archive_path.read_bytes()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        names = tar.getnames()
    assert "manifest.json" in names
    assert "checksum.sha256" in names
    assert "bundle.sig" in names
    assert any(n.startswith("photos/sku-a/") for n in names)
    assert any(n.startswith("photos/sku-b/") for n in names)

    # Verifies as the Pad importer would.
    pub = bundle_signing.load_public_key()
    manifest = bundle_service.verify_bundle_archive(archive, pub)
    assert {s["item_number"] for s in manifest["skus"]} == {"ITEM-A", "ITEM-B"}
    assert manifest["signing_key_fingerprint"] == exported.record.signing_key_fingerprint


def test_only_active_revisions_ship(db_session, tmp_path, bundle_store):
    _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "Widget A", active=True)
    _seed_sku(db_session, tmp_path, "default", "sku-draft", "ITEM-D", "Draft", active=False)
    exported = bundle_service.export_bundle(db_session, tenant_id="default")
    ids = {s["sku_id"] for s in exported.manifest["skus"]}
    assert ids == {"sku-a"}


def test_missing_photo_file_fails_closed(db_session, tmp_path, bundle_store):
    _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A", with_photo=True, photo_missing=True)
    with pytest.raises(bundle_service.BundleExportError):
        bundle_service.export_bundle(db_session, tenant_id="default")


def test_tampered_manifest_fails_verification(db_session, tmp_path, bundle_store):
    _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A")
    _seed_sku(db_session, tmp_path, "default", "sku-b", "ITEM-B", "B")
    archive = bundle_service.export_bundle(db_session, tenant_id="default").archive_path.read_bytes()
    tampered = _rewrite_member(archive, "manifest.json", lambda b: b.replace(b"ITEM-A", b"ITEM-X"))
    pub = bundle_signing.load_public_key()
    with pytest.raises(bundle_service.BundleVerifyError):
        bundle_service.verify_bundle_archive(tampered, pub)


def test_tampered_photo_fails_verification(db_session, tmp_path, bundle_store):
    _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A")
    archive = bundle_service.export_bundle(db_session, tenant_id="default").archive_path.read_bytes()
    photo_name = _first_photo_member(archive)
    tampered = _rewrite_member(archive, photo_name, lambda b: b + b"-EVIL")
    pub = bundle_signing.load_public_key()
    with pytest.raises(bundle_service.BundleVerifyError):
        bundle_service.verify_bundle_archive(tampered, pub)


def test_wrong_key_fails_verification(db_session, tmp_path, bundle_store):
    _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A")
    archive = bundle_service.export_bundle(db_session, tenant_id="default").archive_path.read_bytes()
    _, other_pub_pem = bundle_signing.generate_keypair_pem()
    from cryptography.hazmat.primitives import serialization
    other_pub = serialization.load_pem_public_key(other_pub_pem)
    with pytest.raises(bundle_service.BundleVerifyError):
        bundle_service.verify_bundle_archive(archive, other_pub)


def test_monotonic_version_and_latest(db_session, tmp_path, bundle_store):
    _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A")
    v1 = bundle_service.export_bundle(db_session, tenant_id="default").record.bundle_version
    v2 = bundle_service.export_bundle(db_session, tenant_id="default").record.bundle_version
    assert (v1, v2) == (1, 2)
    assert bundle_service.latest_bundle(db_session, "default").bundle_version == 2


# ── Tests: reverse-sync ingest ─────────────────────────────────────────────────


def _pad_job(job_uuid, sku_id, rev_id, points):
    return {
        "job_uuid": job_uuid,
        "sku_id": sku_id,
        "active_standard_revision_id": rev_id,
        "overall_result": "pass",
        "created_by": "pad-1",
        "checkpoint_results": [
            {"detection_point_id": p, "result": "pass", "confidence": 0.95} for p in points
        ],
        "media": [{"local_path": "/sdcard/x.jpg", "sha256": "abc"}],
    }


def test_reverse_sync_creates_then_dedupes(db_session, tmp_path):
    rev = _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A", n_points=2, with_photo=False)
    points = ["sku-a-dp0", "sku-a-dp1"]
    job = _pad_job("job-uuid-1", "sku-a", rev, points)

    r1 = result_ingest.ingest_job_batch(db_session, "default", [job])
    assert [x.status for x in r1] == ["created"]

    # Re-upload same UUID → deduped, no second job.
    r2 = result_ingest.ingest_job_batch(db_session, "default", [job])
    assert [x.status for x in r2] == ["duplicate"]

    from src.db.execution_models import QCCheckpointResult, QCFinalReport, QCInspectionJob
    assert db_session.query(QCInspectionJob).filter_by(id="job-uuid-1").count() == 1
    assert db_session.query(QCCheckpointResult).filter_by(job_id="job-uuid-1").count() == 2
    assert db_session.query(QCFinalReport).filter_by(job_id="job-uuid-1").one().overall_result == "pass"


def test_reverse_sync_rejects_unknown_sku_and_point(db_session, tmp_path):
    rev = _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A", n_points=1, with_photo=False)
    bad_sku = _pad_job("j-badsku", "nope", rev, [])
    bad_point = _pad_job("j-badpoint", "sku-a", rev, ["sku-a-dp999"])
    out = result_ingest.ingest_job_batch(db_session, "default", [bad_sku, bad_point])
    assert out[0].status == "rejected" and "sku" in out[0].reason
    assert out[1].status == "rejected" and "detection_point" in out[1].reason


# ── Tests: API endpoints ───────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session):
    from src.api.deps import get_db_dep
    from src.api.main import app

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db_dep] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_api_export_latest_download_publickey(client, db_session, tmp_path, bundle_store):
    _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A")
    _seed_sku(db_session, tmp_path, "default", "sku-b", "ITEM-B", "B")

    r = client.post("/api/v1/qc/bundles/export", json={"tenant_id": "default", "generated_by": "qa"})
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["bundle_version"] == 1 and meta["sku_count"] == 2

    latest = client.get("/api/v1/qc/bundles/latest", params={"tenant_id": "default"}).json()
    assert latest["id"] == meta["id"]

    dl = client.get(meta["download_url"], params={"tenant_id": "default", "downloaded_by": "pad-1"})
    assert dl.status_code == 200
    pub = bundle_signing.load_public_key()
    manifest = bundle_service.verify_bundle_archive(dl.content, pub)
    assert manifest["sku_count"] == 2

    pk = client.get("/api/v1/qc/bundles/public-key").json()
    assert pk["algorithm"] == "ed25519" and pk["fingerprint"] == meta["signing_key_fingerprint"]


def test_api_batch_upload_idempotent(client, db_session, tmp_path):
    rev = _seed_sku(db_session, tmp_path, "default", "sku-a", "ITEM-A", "A", n_points=1, with_photo=False)
    job = _pad_job("api-job-1", "sku-a", rev, ["sku-a-dp0"])
    r1 = client.post("/api/v1/qc/inspection-jobs/batch", json={"tenant_id": "default", "jobs": [job]})
    assert r1.status_code == 200 and r1.json()["created"] == 1
    r2 = client.post("/api/v1/qc/inspection-jobs/batch", json={"tenant_id": "default", "jobs": [job]})
    assert r2.json()["duplicate"] == 1 and r2.json()["created"] == 0


# ── archive rewrite helpers (tamper) ───────────────────────────────────────────


def _first_photo_member(archive: bytes) -> str:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for n in tar.getnames():
            if n.startswith("photos/"):
                return n
    raise AssertionError("no photo member")


def _rewrite_member(archive: bytes, target: str, transform) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as src, \
            tarfile.open(fileobj=out, mode="w:gz") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read()
            if m.name == target:
                data = transform(data)
            info = tarfile.TarInfo(name=m.name)
            info.size = len(data)
            info.mtime = 0
            dst.addfile(info, io.BytesIO(data))
    return out.getvalue()
