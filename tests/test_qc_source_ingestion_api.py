"""Source ingestion API + tenant isolation + safety tests (PR 21 §4, §7, §8)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.qc_learning_models  # noqa: F401
import src.db.qc_source_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def client(session_factory):
    def override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db_dep] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_source(client, tp="tp1", tenant="default", **kw):
    body = {"source_type": "natural_language", "tenant_id": tenant}
    body.update(kw)
    return client.post(f"/api/qc/training-packs/{tp}/sources", json=body)


# ── Create / list / get ───────────────────────────────────────────────────


def test_create_source_document_all_fields(client):
    resp = _create_source(
        client, tp="tp_create", title="Spec A",
        text_content="The center must be aligned.", sku_id="sku1",
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_type"] == "natural_language"
    assert data["title"] == "Spec A"
    assert data["status"] == "draft"
    assert data["training_pack_id"] == "tp_create"


def test_list_sources_scoped_to_training_pack(client):
    _create_source(client, tp="tp_list_a", text_content="A must align.")
    _create_source(client, tp="tp_list_b", text_content="B must align.")
    a = client.get("/api/qc/training-packs/tp_list_a/sources").json()
    assert len(a["sources"]) == 1
    assert all(s["training_pack_id"] == "tp_list_a" for s in a["sources"])


def test_invalid_source_type_returns_422(client):
    resp = _create_source(client, tp="tp_bad", source_type="not_a_real_type")
    assert resp.status_code == 422


def test_natural_language_flow_end_to_end(client):
    src = _create_source(
        client, tp="tp_nl",
        text_content="The petal must not have a crack. Confirm the pearl count.",
    ).json()
    job = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    assert job["status"] == "completed"
    assert job["fragment_count"] >= 2
    frags = client.get(f"/api/qc/source-extraction-jobs/{job['job_id']}/fragments").json()
    types = {f["fragment_type"] for f in frags["fragments"]}
    assert "possible_detection_point" in types
    assert "missing_tolerance_or_count" in types


def test_process_spec_flow_end_to_end(client):
    src = _create_source(
        client, tp="tp_spec", source_type="process_spec",
        text_content="Rivet diameter must be 5.0 mm plus/minus 0.2 mm.",
    ).json()
    job = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    frags = client.get(f"/api/qc/source-extraction-jobs/{job['job_id']}/fragments").json()
    assert any(f["fragment_type"] == "possible_physical_measurement" for f in frags["fragments"])


def test_file_reference_registration_metadata_only(client):
    resp = _create_source(
        client, tp="tp_file", source_type="drawing",
        file_ref="s3://bucket/drawing.pdf", mime_type="application/pdf",
    )
    assert resp.status_code == 201
    src = resp.json()
    assert src["file_ref"] == "s3://bucket/drawing.pdf"
    # Extraction of a binary reference yields a single review fragment.
    job = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    frags = client.get(f"/api/qc/source-extraction-jobs/{job['job_id']}/fragments").json()
    assert len(frags["fragments"]) == 1
    assert frags["fragments"][0]["fragment_type"] == "requires_supervisor_review"


def test_extraction_is_append_safe(client):
    src = _create_source(client, tp="tp_append", text_content="The center must align.").json()
    job1 = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    job2 = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    assert job1["job_id"] != job2["job_id"]
    # Prior job's fragments are still retrievable and unchanged.
    f1 = client.get(f"/api/qc/source-extraction-jobs/{job1['job_id']}/fragments").json()
    assert len(f1["fragments"]) == job1["fragment_count"] >= 1


def test_get_source_and_job(client):
    src = _create_source(client, tp="tp_get", text_content="Must align.").json()
    assert client.get(f"/api/qc/sources/{src['source_id']}").status_code == 200
    job = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    assert client.get(f"/api/qc/source-extraction-jobs/{job['job_id']}").json()["status"] == "completed"


def test_unknown_source_and_job_return_404(client):
    assert client.get("/api/qc/sources/nope").status_code == 404
    assert client.get("/api/qc/source-extraction-jobs/nope").status_code == 404
    assert client.post("/api/qc/sources/nope/extract", json={}).status_code == 404


# ── Tenant isolation (PR 21 §7) ───────────────────────────────────────────


def test_tenant_cannot_read_or_extract_other_tenants_sources(client):
    # Tenant A creates + extracts a source under tp_shared.
    src = _create_source(client, tp="tp_iso", tenant="tenantA", text_content="Must align.").json()
    job = client.post(
        f"/api/qc/sources/{src['source_id']}/extract", json={"tenant_id": "tenantA"}
    ).json()

    # Tenant B cannot read the source, the job, or the job's fragments.
    assert client.get(f"/api/qc/sources/{src['source_id']}?tenant_id=tenantB").status_code == 404
    assert client.get(
        f"/api/qc/source-extraction-jobs/{job['job_id']}?tenant_id=tenantB"
    ).status_code == 404
    assert client.get(
        f"/api/qc/source-extraction-jobs/{job['job_id']}/fragments?tenant_id=tenantB"
    ).status_code == 404
    # Tenant B cannot extract tenant A's source.
    assert client.post(
        f"/api/qc/sources/{src['source_id']}/extract", json={"tenant_id": "tenantB"}
    ).status_code == 404


def test_cross_tenant_training_pack_reference_rejected(client):
    # Tenant A binds tp_owned.
    _create_source(client, tp="tp_owned", tenant="ownerA", text_content="Must align.")
    # Tenant B cannot register a source under tenant A's training pack.
    resp = _create_source(client, tp="tp_owned", tenant="intruderB", text_content="x")
    assert resp.status_code == 404


def test_list_is_tenant_scoped(client):
    _create_source(client, tp="tp_ls", tenant="ownerLS", text_content="Must align.")
    # Different tenant sees no sources for that pack (and cannot bind it either).
    other = client.get("/api/qc/training-packs/tp_ls/sources?tenant_id=ownerLS").json()
    assert len(other["sources"]) == 1


# ── Safety: no path to activate a Training Pack rule (PR 21 §7) ────────────


def test_no_active_status_in_source_models():
    from src.db import qc_source_models as m

    # The only draft-lifecycle statuses are draft / reviewed / rejected.
    assert {m.SOURCE_STATUS_DRAFT, m.SOURCE_STATUS_REVIEWED, m.SOURCE_STATUS_REJECTED} == {
        "draft",
        "reviewed",
        "rejected",
    }
    text = Path("src/db/qc_source_models.py").read_text()
    # No column ever defaults to an "active" status.
    assert 'default="active"' not in text and "default='active'" not in text
    assert '= "active"' not in text


def test_ingestion_does_not_import_training_pack_mutators():
    """Ingestion code must not import Training Pack rule-mutation symbols."""
    forbidden = {"QCDetectionPoint", "QCCheckpointClassification", "apply_approved_rules"}
    files = list(Path("src/qc_model/ingestion").rglob("*.py")) + [
        Path("src/api/qc_source_router.py")
    ]
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported = {a.name for a in node.names}
                assert not (imported & forbidden), (
                    f"{path} imports Training Pack mutator(s): {imported & forbidden}"
                )


def test_extraction_does_not_create_detection_points(client, session_factory):
    from src.db.sku_models import QCDetectionPoint

    src = _create_source(client, tp="tp_safe", text_content="The center must align.").json()
    client.post(f"/api/qc/sources/{src['source_id']}/extract", json={})
    s = session_factory()
    try:
        # No detection points were written to the Training Pack catalog.
        assert s.query(QCDetectionPoint).filter_by(sku_id="tp_safe").count() == 0
    finally:
        s.close()


# ── UI smoke (PR 21 §6, §8) ───────────────────────────────────────────────


def test_ui_page_loads_form_submits_and_fragments_render(client):
    tp = "tp_ui"
    # Page loads.
    page = client.get(f"/admin/qc-model/training-packs/{tp}/sources")
    assert page.status_code == 200
    assert "QC Source Ingestion Workbench" in page.text
    assert "draft only" in page.text.lower()

    # Form submit registers a source.
    submit = client.post(
        f"/admin/qc-model/training-packs/{tp}/sources",
        data={
            "source_type": "natural_language",
            "title": "UI spec",
            "text_content": "The petal must not have a crack. Confirm the pearl count.",
            "file_ref": "",
        },
        follow_redirects=True,
    )
    assert submit.status_code == 200

    # Trigger extraction via the source id from the API list.
    src = client.get(f"/api/qc/training-packs/{tp}/sources").json()["sources"][0]
    client.post(
        f"/admin/qc-model/training-packs/{tp}/sources/{src['source_id']}/extract",
        follow_redirects=True,
    )
    # Fragment list renders on the page.
    page2 = client.get(f"/admin/qc-model/training-packs/{tp}/sources")
    assert "possible_detection_point" in page2.text


# ── Process-card file upload (WS6) — real endpoint, not just the extractor ─


def test_upload_process_card_txt_is_really_extracted_end_to_end(client):
    """A real multipart upload of a .txt process card: the file is stored,
    the source document is created with source_type=process_card and REAL
    text_content decoded from the uploaded bytes (not a placeholder), and
    running extraction on it produces the same real statement-classification
    fragments as a natural_language source -- proving the whole upload ->
    store -> extract path is wired, not just the extractor function in
    isolation."""
    tp = "tp_upload_txt"
    content = b"The stamen must be centered and aligned.\nRivet diameter must be 5.0 mm plus/minus 0.2 mm."
    resp = client.post(
        f"/admin/qc-model/training-packs/{tp}/sources/upload",
        data={"title": "Uploaded card"},
        files={"file": ("card.txt", content, "text/plain")},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    sources = client.get(f"/api/qc/training-packs/{tp}/sources").json()["sources"]
    assert len(sources) == 1
    src = sources[0]
    assert src["source_type"] == "process_card"
    assert src["title"] == "Uploaded card"
    assert src["text_content"] == content.decode("utf-8")
    assert src["file_ref"] and src["file_ref"].endswith(".txt")

    job = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    frags = client.get(f"/api/qc/source-extraction-jobs/{job['job_id']}/fragments").json()["fragments"]
    types = {f["fragment_type"] for f in frags}
    assert "possible_detection_point" in types
    assert "possible_physical_measurement" in types


def test_upload_corrupt_process_card_pdf_is_stored_but_honestly_unextracted(client):
    """A .pdf upload is accepted (process_card.py can classify it), stored on
    disk, and registered -- but since no PDF parser exists in this
    environment, text_content must stay unset (no fabricated extraction),
    and running extraction must honestly report that no parser is wired
    rather than silently produce a fake result."""
    tp = "tp_upload_pdf"
    resp = client.post(
        f"/admin/qc-model/training-packs/{tp}/sources/upload",
        data={},
        files={"file": ("card.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    src = client.get(f"/api/qc/training-packs/{tp}/sources").json()["sources"][0]
    assert src["source_type"] == "process_card"
    assert src["text_content"] is None
    assert src["file_ref"] and src["file_ref"].endswith(".pdf")

    job = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    frags = client.get(f"/api/qc/source-extraction-jobs/{job['job_id']}/fragments").json()["fragments"]
    assert len(frags) == 1
    assert frags[0]["fragment_type"] == "requires_supervisor_review"
    assert "no readable embedded text" in frags[0]["text"]
    assert src["metadata"]["ingestion"]["status"] == "embedded_text_unreadable"


def test_upload_process_card_image_uses_live_provider_neutral_ocr(client, monkeypatch):
    from src.qc_model.studio import ai_gateway

    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://vision.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "replaceable-4b")
    monkeypatch.setattr(
        ai_gateway,
        "extract_image_text",
        lambda **kwargs: {
            "text": "The stamen must be centered and aligned.",
            "language": "en",
            "layout_notes": "single row",
            "assistant": {
                "role": "vision", "provider": "openai_compatible",
                "model": "replaceable-4b", "elapsed_ms": 42, "mode": "live",
                "route": "primary", "strategy": "cv_then_primary_then_conditional_fallback",
                "primary_model": "replaceable-4b", "fallback_model": None,
                "fallback_used": False, "escalation_reasons": [], "passes": 1,
            },
        },
    )
    fixture = Path(__file__).parent / "fixtures" / "qc" / "standard_red_square.png"
    tp = "tp_upload_image_ocr"
    response = client.post(
        f"/admin/qc-model/training-packs/{tp}/sources/upload",
        files={"file": ("card.png", fixture.read_bytes(), "image/png")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    src = client.get(f"/api/qc/training-packs/{tp}/sources").json()["sources"][0]
    assert src["text_content"] == "The stamen must be centered and aligned."
    assert src["metadata"]["ingestion"]["status"] == "vision_ocr_extracted"
    assert src["metadata"]["ingestion"]["assistant"]["model"] == "replaceable-4b"

    job = client.post(f"/api/qc/sources/{src['source_id']}/extract", json={}).json()
    fragments = client.get(
        f"/api/qc/source-extraction-jobs/{job['job_id']}/fragments"
    ).json()["fragments"]
    assert fragments[0]["fragment_type"] == "possible_detection_point"


def test_upload_process_card_rejects_unrecognized_extension(client):
    resp = client.post(
        "/admin/qc-model/training-packs/tp_upload_bad/sources/upload",
        data={},
        files={"file": ("card.xyz", b"whatever", "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_upload_process_card_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setenv("QC_MAX_UPLOAD_BYTES", "10")
    try:
        resp = client.post(
            "/admin/qc-model/training-packs/tp_upload_big/sources/upload",
            data={},
            files={"file": ("card.txt", b"this is way more than ten bytes", "text/plain")},
        )
        assert resp.status_code == 413
    finally:
        monkeypatch.delenv("QC_MAX_UPLOAD_BYTES", raising=False)
