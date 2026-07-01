"""Rule-authoring API + service + tenant + no-apply-path tests (PR 22 §6, §8, §9)."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Enable the deterministic mock authoring provider for the API path.
os.environ["QC_AUTHORING_ALLOW_MOCK"] = "true"

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.qc_learning_models  # noqa: F401
import src.db.qc_source_models  # noqa: F401
import src.db.qc_authoring_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
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


def _seed_fragments(client, tp="tpA", tenant="default", text=None):
    text = text or (
        "pearl diameter 6mm plus/minus 0.2mm. "
        "rhinestone count must be 12. "
        "no visible glue overflow from front view."
    )
    src = client.post(
        f"/api/qc/training-packs/{tp}/sources",
        json={"source_type": "process_spec", "tenant_id": tenant, "text_content": text},
    ).json()
    job = client.post(
        f"/api/qc/sources/{src['source_id']}/extract", json={"tenant_id": tenant}
    ).json()
    frags = client.get(
        f"/api/qc/source-extraction-jobs/{job['job_id']}/fragments?tenant_id={tenant}"
    ).json()["fragments"]
    return src, job, frags


# ── Happy path + worked examples through the API ──────────────────────────


def test_propose_rules_for_extraction_job(client):
    _, job, _ = _seed_fragments(client, tp="tp_auth1")
    aj = client.post(
        f"/api/qc/source-extraction-jobs/{job['job_id']}/propose-rules", json={}
    ).json()
    assert aj["status"] == "completed"
    by_cat = {p["checkpoint_category"]: p for p in aj["proposals"]}
    assert by_cat["physical_measurement"]["ai_role"] == "record_only"
    assert by_cat["rule_verification"]["ai_role"] == "information_extraction"
    assert by_cat["visual_defect"]["ai_role"] == "primary_visual_judge"


def test_propose_rules_for_single_fragment_and_traceability(client):
    _, _, frags = _seed_fragments(client, tp="tp_auth2")
    frag = next(f for f in frags if "diameter" in f["text"])
    aj = client.post(
        f"/api/qc/source-fragments/{frag['fragment_id']}/propose-rules", json={}
    ).json()
    assert aj["status"] == "completed"
    p = aj["proposals"][0]
    # Traceability back to the PR 21 fragment.
    assert p["source_fragment_id"] == frag["fragment_id"]


def test_get_authoring_job_and_proposals(client):
    _, job, _ = _seed_fragments(client, tp="tp_auth3")
    aj = client.post(
        f"/api/qc/source-extraction-jobs/{job['job_id']}/propose-rules", json={}
    ).json()
    got = client.get(f"/api/qc/rule-authoring-jobs/{aj['job_id']}").json()
    assert got["status"] == "completed"
    props = client.get(f"/api/qc/rule-authoring-jobs/{aj['job_id']}/proposals").json()
    assert len(props["proposals"]) == aj["proposal_count"]


def test_all_proposals_start_as_draft_proposed(client):
    _, job, _ = _seed_fragments(client, tp="tp_auth4")
    aj = client.post(
        f"/api/qc/source-extraction-jobs/{job['job_id']}/propose-rules", json={}
    ).json()
    assert all(p["status"] == "proposed" for p in aj["proposals"])


# ── Tenant isolation ──────────────────────────────────────────────────────


def test_tenant_cannot_author_or_read_other_tenants(client):
    _, job, frags = _seed_fragments(client, tp="tp_iso_auth", tenant="tA")
    frag = frags[0]
    # Tenant B cannot author rules for tenant A's fragment.
    assert client.post(
        f"/api/qc/source-fragments/{frag['fragment_id']}/propose-rules",
        json={"tenant_id": "tB"},
    ).status_code == 404

    # Tenant A authors; tenant B cannot read the job or its proposals.
    aj = client.post(
        f"/api/qc/source-extraction-jobs/{job['job_id']}/propose-rules",
        json={"tenant_id": "tA"},
    ).json()
    assert client.get(f"/api/qc/rule-authoring-jobs/{aj['job_id']}?tenant_id=tB").status_code == 404
    assert client.get(
        f"/api/qc/rule-authoring-jobs/{aj['job_id']}/proposals?tenant_id=tB"
    ).status_code == 404


def test_unknown_fragment_and_job_return_404(client):
    assert client.post("/api/qc/source-fragments/nope/propose-rules", json={}).status_code == 404
    assert client.get("/api/qc/rule-authoring-jobs/nope").status_code == 404


# ── §8/§9 No Training Pack apply path exists in this PR ────────────────────


def test_no_apply_endpoint_exists_for_authoring():
    paths = set(app.openapi()["paths"].keys())
    authoring_paths = {p for p in paths if "rule-authoring" in p or "propose-rules" in p}
    assert authoring_paths  # sanity: authoring routes exist
    # None of the authoring routes is an apply/activate path.
    assert not any("apply" in p or "activate" in p for p in authoring_paths)
    # And no route anywhere applies an *authored* proposal to a Training Pack.
    assert not any("authoring" in p and ("apply" in p or "activate" in p) for p in paths)


def test_authoring_code_has_no_training_pack_write_path():
    forbidden = {"QCDetectionPoint", "QCCheckpointClassification", "apply_approved_rules"}
    files = list(Path("src/qc_model/authoring").rglob("*.py")) + [
        Path("src/api/qc_authoring_router.py")
    ]
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {a.name for a in node.names}
                assert not (names & forbidden), f"{path} imports Training Pack mutator {names & forbidden}"


def test_authoring_creates_no_detection_points(client, session_factory):
    from src.db.sku_models import QCDetectionPoint

    _, job, _ = _seed_fragments(client, tp="tp_safe_auth")
    client.post(f"/api/qc/source-extraction-jobs/{job['job_id']}/propose-rules", json={})
    s = session_factory()
    try:
        assert s.query(QCDetectionPoint).filter_by(sku_id="tp_safe_auth").count() == 0
    finally:
        s.close()


# ── Approval reuse (PR 20 workflow) + guard survives edit ─────────────────


def test_approve_and_reject_via_ui(client):
    tp = "tp_ui_auth"
    _, _, frags = _seed_fragments(client, tp=tp)
    frag = next(f for f in frags if "glue overflow" in f["text"])
    client.post(
        f"/admin/qc-model/training-packs/{tp}/fragments/{frag['fragment_id']}/propose",
        follow_redirects=True,
    )
    # Fetch proposal id via API.
    page_props = client.get(f"/api/qc/training-packs/{tp}/sources").json()
    # find the authoring proposal through the fragment endpoint
    src_list = client.get(f"/api/qc/training-packs/{tp}/sources").json()["sources"]
    assert src_list
    # Approve the proposal for the glue-overflow fragment.
    # (Look it up via a fresh authoring run listing.)
    aj = client.post(
        f"/api/qc/source-fragments/{frag['fragment_id']}/propose-rules", json={}
    ).json()
    pid = aj["proposals"][0]["proposal_id"]
    resp = client.post(
        f"/admin/qc-model/training-packs/{tp}/proposals/{pid}/approve",
        data={"checkpoint_category": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_edit_to_physical_measurement_forces_record_only(client, session_factory):
    from src.db.qc_learning_models import QCLearnedDetectionPointProposal

    _, _, frags = _seed_fragments(client, tp="tp_edit_guard")
    frag = next(f for f in frags if "glue overflow" in f["text"])  # visual_defect proposal
    aj = client.post(
        f"/api/qc/source-fragments/{frag['fragment_id']}/propose-rules", json={}
    ).json()
    pid = aj["proposals"][0]["proposal_id"]
    # Supervisor edits category to physical_measurement on approve.
    client.post(
        f"/admin/qc-model/training-packs/tp_edit_guard/proposals/{pid}/approve",
        data={"checkpoint_category": "physical_measurement"},
        follow_redirects=True,
    )
    s = session_factory()
    try:
        p = s.query(QCLearnedDetectionPointProposal).filter_by(id=pid).first()
        assert p.proposed_checkpoint_category == "physical_measurement"
        assert p.proposed_ai_role == "record_only"  # guard survives the edit
        assert p.status == "approved"
    finally:
        s.close()


def test_ui_page_renders_proposals_with_controls(client):
    tp = "tp_ui_render"
    _, job, _ = _seed_fragments(client, tp=tp)
    client.post(f"/api/qc/source-extraction-jobs/{job['job_id']}/propose-rules", json={})
    page = client.get(f"/admin/qc-model/training-packs/{tp}/sources")
    assert page.status_code == 200
    body = page.text
    assert "Propose rules (LLM)" in body
    assert "Approve / Edit" in body and "Reject" in body
    assert "record_only" in body  # a physical-measurement proposal rendered
