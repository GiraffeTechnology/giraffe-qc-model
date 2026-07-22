"""Tests for the Stage 3 Group A real-device harness
(scripts/jetson_stage3_run_group_a.py).

The strongest available check without real hardware: build a real Ed25519
keypair and use the actual server-side ``AdminAuthenticator`` from
``jetson_runner/app/admin_auth.py`` to verify a request the harness signed —
proving compatibility with the real verifier, not a re-derived guess at the
contract. Network calls are stubbed (``call_recognitions`` monkeypatched);
no real hardware or HTTP is touched.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses' __module__ lookup needs this registered
    spec.loader.exec_module(mod)
    return mod


harness = _load("scripts/jetson_stage3_run_group_a.py", "group_a_harness")
admin_auth = _load("jetson_runner/app/admin_auth.py", "admin_auth_mod")
gate = _load("scripts/ci/stage3_authorization_gate.py", "stage3_gate")


@pytest.fixture()
def keypair():
    private = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(
        private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    return private, public_b64


def test_build_manifest_shape():
    manifest = harness.build_manifest(
        request_id="req-1", workflow="qualification_review",
        standard_revision_id="rev-1", bundle_version="v1",
        image_id="primary", part="front.jpg", image_bytes=b"abc",
        content_type="image/jpeg",
        detection_points=[{"point_code": "dp1", "image_id": "primary"}],
    )
    assert manifest["schema_version"] == "2.0"
    assert manifest["images"][0]["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert manifest["images"][0]["encoded_bytes"] == 3
    assert manifest["detection_points"][0]["point_code"] == "dp1"


def test_signed_request_is_accepted_by_the_real_admin_authenticator(keypair):
    """Proves harness.sign_headers() is compatible with the real server verifier."""
    private, public_b64 = keypair
    authenticator = admin_auth.AdminAuthenticator({
        "test-bearer": {
            "tenant_id": "t1", "subject": "jetson-harness", "key_id": "key-1",
            "public_key": public_b64,
        }
    })
    manifest = harness.build_manifest(
        request_id="req-42", workflow="qualification_review",
        standard_revision_id="rev-1", bundle_version="v1",
        image_id="primary", part="front.jpg", image_bytes=b"image-bytes",
        content_type="image/jpeg",
        detection_points=[{"point_code": "dp1", "image_id": "primary"}],
    )
    path = "/api/v2/admin-runner/recognitions"
    headers, digest = harness.sign_headers(
        admin_auth, private, key_id="key-1", bearer="test-bearer",
        method="POST", path=path, manifest=manifest,
    )

    principal = authenticator.authenticate(
        method="POST", path=path, headers=headers,
        content_sha256=digest, request_id=manifest["request_id"],
    )
    assert principal.subject == "jetson-harness"
    assert principal.key_id == "key-1"


def test_signed_request_with_tampered_manifest_is_rejected(keypair):
    """A manifest changed after signing must fail server-side verification —
    proves the digest genuinely binds to manifest content."""
    private, public_b64 = keypair
    authenticator = admin_auth.AdminAuthenticator({
        "test-bearer": {
            "tenant_id": "t1", "subject": "jetson-harness", "key_id": "key-1",
            "public_key": public_b64,
        }
    })
    manifest = harness.build_manifest(
        request_id="req-42", workflow="qualification_review",
        standard_revision_id="rev-1", bundle_version="v1",
        image_id="primary", part="front.jpg", image_bytes=b"image-bytes",
        content_type="image/jpeg",
        detection_points=[{"point_code": "dp1", "image_id": "primary"}],
    )
    path = "/api/v2/admin-runner/recognitions"
    headers, _digest = harness.sign_headers(
        admin_auth, private, key_id="key-1", bearer="test-bearer",
        method="POST", path=path, manifest=manifest,
    )
    tampered_manifest = dict(manifest, standard_revision_id="rev-ATTACKER")
    tampered_digest = admin_auth.multipart_content_sha256(tampered_manifest)

    with pytest.raises(admin_auth.AdminAuthRejected):
        authenticator.authenticate(
            method="POST", path=path, headers=headers,
            content_sha256=tampered_digest, request_id=manifest["request_id"],
        )


def test_run_case_records_success_without_network(tmp_path, keypair, monkeypatch):
    private, _public_b64 = keypair
    image = tmp_path / "front.jpg"
    image.write_bytes(b"jpeg-bytes")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    def fake_call_recognitions(base_url, headers, manifest, image_bytes, part, content_type, timeout):
        return {
            "schema_version": "2.0", "request_id": manifest["request_id"], "status": "completed",
            "point_results": [{"point_code": "dp1", "result": "pass", "confidence": 0.9, "evidence": ""}],
            "runtime": {"engine": "mnn", "model_name": "qwen3-vl-4b", "model_revision": "rev-x", "adapter_mode": "real"},
            "timing": {
                "request_received_at": "t", "inference_started_at": "t",
                "inference_completed_at": "t", "response_sent_at": "t",
            },
            "mock": False,
        }

    monkeypatch.setattr(harness, "call_recognitions", fake_call_recognitions)

    result, ok, raw = harness.run_case(
        admin_auth=admin_auth, private_key=private, base_url="http://127.0.0.1:8600",
        key_id="key-1", bearer="test-bearer", workflow="qualification_review",
        standard_revision_id="rev-1", bundle_version="v1",
        case={"case_id": "c1", "image_path": str(image), "detection_points": [{"point_code": "dp1", "image_id": "primary"}]},
        timeout=5.0, evidence_dir=evidence_dir,
    )
    assert ok is True
    assert result["verdict"] == "pass"
    assert result["passed"] is True
    assert Path(result["request_ref"]).exists()
    assert Path(result["response_ref"]).exists()


def test_run_case_records_failure_without_fabricating_pass(tmp_path, keypair, monkeypatch):
    private, _public_b64 = keypair
    image = tmp_path / "front.jpg"
    image.write_bytes(b"jpeg-bytes")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    def fake_call_recognitions(*args, **kwargs):
        raise ConnectionRefusedError("device unreachable")

    monkeypatch.setattr(harness, "call_recognitions", fake_call_recognitions)

    result, ok, raw = harness.run_case(
        admin_auth=admin_auth, private_key=private, base_url="http://127.0.0.1:8600",
        key_id="key-1", bearer="test-bearer", workflow="qualification_review",
        standard_revision_id="rev-1", bundle_version="v1",
        case={"case_id": "c1", "image_path": str(image), "detection_points": []},
        timeout=5.0, evidence_dir=evidence_dir,
    )
    assert ok is False
    assert raw is None
    assert result["passed"] is False
    assert result["verdict"] == "reject"
    assert "ConnectionRefusedError" in result["anomaly_notes"][0]


def test_verdict_from_points_rejects_on_fail():
    assert harness._verdict_from_points({"point_results": [{"result": "fail"}]}) == "reject"
    assert harness._verdict_from_points({"point_results": [{"result": "pass"}]}) == "pass"
    assert harness._verdict_from_points(None) == "reject"
    assert harness._verdict_from_points({}) == "reject"


def test_main_refuses_when_authorization_gate_is_closed(tmp_path, monkeypatch):
    """The gate check must run before any network/signing work, and the
    harness must exit non-zero without writing a report."""
    output = tmp_path / "report.json"

    class _ClosedGate:
        open = False
        def summary(self):
            return "CLOSED — test"

    monkeypatch.setattr(gate, "evaluate", lambda: _ClosedGate())
    monkeypatch.setattr(harness, "_load_module", lambda rel, name: gate if "authorization_gate" in rel else None)

    argv = [
        "--bearer", "x", "--key-id", "k", "--private-key-path", "/nonexistent",
        "--standard-revision-id", "rev-1", "--cases", str(tmp_path / "cases.json"),
        "--model-manifest", str(tmp_path / "manifest.json"),
        "--model-backend", "cpu", "--output", str(output),
    ]
    monkeypatch.setattr("sys.argv", ["jetson_stage3_run_group_a.py", *argv])
    exit_code = harness.main()
    assert exit_code == 1
    assert not output.exists()
