from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from jetson_runner.app.adapters.mnn_adapter import MnnVlmAdapter
from jetson_runner.app.admin_auth import (
    EMPTY_SHA256,
    AdminAuthRejected,
    AdminAuthenticator,
    multipart_content_sha256,
    signature_payload,
)
from jetson_runner.app.admin_contract import AdminRecognitionRequest
from jetson_runner.app.config import RunnerConfig
from jetson_runner.app.identity import generate_identity
from jetson_runner.app.main import AdminRequestRejected, JetsonRunnerService, build_app


class FakeMnnRuntime:
    def __init__(self, outputs: list[str] | None = None, ready: bool = True):
        self.outputs = list(outputs or [])
        self.ready = ready
        self.prompts: list[str] = []
        self.images: list[str] = []

    @property
    def last_error(self) -> str:
        return "fixture_not_ready" if not self.ready else ""

    def is_ready(self) -> bool:
        return self.ready

    def infer(self, *, image_path: str, prompt: str) -> str:
        self.images.append(image_path)
        self.prompts.append(prompt)
        return self.outputs.pop(0)


def _manifest(data: bytes = b"image-bytes") -> dict:
    return {
        "schema_version": "2.0",
        "request_id": "adminrec-1",
        "workflow": "authoring_validation",
        "standard_revision_id": "rev-1",
        "bundle_version": "v1",
        "images": [
            {
                "image_id": "front",
                "part": "front.jpg",
                "sha256": hashlib.sha256(data).hexdigest(),
                "content_type": "image/jpeg",
                "encoded_bytes": len(data),
            }
        ],
        "detection_points": [
            {
                "point_code": "stones",
                "image_id": "front",
                "label": "Stone count",
                "expected_value": "24",
                "pass_criteria": "all present",
                "expected_features": {"count": 24},
                "cv_status": "completed",
                "cv_analysis": {"analyzer": "count", "count": 24},
            }
        ],
    }


def test_mnn_adapter_is_provider_neutral_and_includes_cv_context(tmp_path):
    (tmp_path / "model_manifest.json").write_text('{"revision":"rev-abc"}', encoding="utf-8")
    runtime = FakeMnnRuntime(
        ['{"result":"pass","confidence":0.91,"evidence":"24 visible"}']
    )
    adapter = MnnVlmAdapter(
        bridge_library="unused-in-test",
        model_dir=str(tmp_path),
        model_name="replaceable-vlm",
        runtime=runtime,
    )
    request = AdminRecognitionRequest.model_validate(_manifest())
    result = adapter.run_admin_recognition(request, {"front": "/tmp/front.jpg"})[0]
    assert adapter.adapter_name == "mnn"
    assert adapter.model_name == "replaceable-vlm"
    assert adapter.model_revision == "rev-abc"
    assert result.result == "pass"
    assert "<CV_PREANALYSIS_JSON>" in runtime.prompts[0]
    assert '"count":24' in runtime.prompts[0]


def test_mnn_invalid_model_output_is_uncertain_not_a_synthetic_verdict(tmp_path):
    runtime = FakeMnnRuntime(["not-json"])
    adapter = MnnVlmAdapter(
        bridge_library="unused", model_dir=str(tmp_path), model_name="configured-vlm", runtime=runtime
    )
    result = adapter.run_admin_recognition(
        AdminRecognitionRequest.model_validate(_manifest()), {"front": "/tmp/front.jpg"}
    )[0]
    assert result.result == "uncertain"
    assert result.confidence == 0.0


def _credentials():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    credentials = {
        "test-token": {
            "tenant_id": "tenant-1",
            "subject": "admin-device-1",
            "key_id": "key-1",
            "public_key": base64.b64encode(public).decode("ascii"),
        }
    }
    return private, credentials


def _headers(private, *, method: str, path: str, digest: str, request_id: str = "", nonce="n-1"):
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    signature = private.sign(
        signature_payload(method, path, timestamp, nonce, digest, request_id)
    )
    return {
        "Authorization": "Bearer test-token",
        "X-QC-Key-Id": "key-1",
        "X-QC-Timestamp": timestamp,
        "X-QC-Nonce": nonce,
        "X-QC-Content-SHA256": digest,
        "X-QC-Signature": base64.b64encode(signature).decode("ascii"),
    }


def test_admin_auth_rejects_replayed_nonce():
    private, credentials = _credentials()
    auth = AdminAuthenticator(credentials)
    headers = _headers(
        private, method="GET", path="/api/v2/admin-runner/health", digest=EMPTY_SHA256
    )
    auth.authenticate(
        method="GET",
        path="/api/v2/admin-runner/health",
        headers=headers,
        content_sha256=EMPTY_SHA256,
    )
    with pytest.raises(AdminAuthRejected, match="replay_detected"):
        auth.authenticate(
            method="GET",
            path="/api/v2/admin-runner/health",
            headers=headers,
            content_sha256=EMPTY_SHA256,
        )


def _mock_client():
    private, credentials = _credentials()
    cfg = RunnerConfig(mock_mode=True, admin_credentials=credentials)
    service = JetsonRunnerService(cfg, identity=generate_identity("xavier-test"))
    return private, TestClient(build_app(cfg, service))


def test_signed_admin_health_is_truthful_about_mock_and_validation():
    private, client = _mock_client()
    path = "/api/v2/admin-runner/health"
    response = client.get(
        path,
        headers=_headers(private, method="GET", path=path, digest=EMPTY_SHA256),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runtime"]["engine"] == "mnn"
    assert body["runtime"]["adapter_mode"] == "mock"
    assert body["hardware_validation"]["status"] == "not_run"
    assert body["cv_pipeline"]["status"] == "not_configured"
    assert body["mock"] is True


def test_admin_recognition_validates_image_and_labels_mock(caplog):
    private, client = _mock_client()
    data = b"image-bytes"
    manifest = _manifest(data)
    path = "/api/v2/admin-runner/recognitions"
    digest = multipart_content_sha256(manifest)
    response = client.post(
        path,
        headers=_headers(
            private,
            method="POST",
            path=path,
            digest=digest,
            request_id=manifest["request_id"],
        ),
        data={"manifest": json.dumps(manifest)},
        files=[("images", ("front.jpg", data, "image/jpeg"))],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mock"] is True
    assert body["warning"] == "MOCK INFERENCE — NOT REAL QC JUDGMENT"
    assert body["point_results"][0]["result"] == "uncertain"
    assert "MOCK INFERENCE — NOT REAL QC JUDGMENT" in body["point_results"][0]["evidence"]
    assert any("MOCK INFERENCE — NOT REAL QC JUDGMENT" in r.message for r in caplog.records)


def test_admin_recognition_rejects_image_digest_mismatch_before_inference():
    private, client = _mock_client()
    manifest = _manifest(b"expected")
    path = "/api/v2/admin-runner/recognitions"
    response = client.post(
        path,
        headers=_headers(
            private,
            method="POST",
            path=path,
            digest=multipart_content_sha256(manifest),
            request_id=manifest["request_id"],
        ),
        data={"manifest": json.dumps(manifest)},
        files=[("images", ("front.jpg", b"different", "image/jpeg"))],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "image_digest_mismatch"


def test_admin_recognition_returns_runner_busy_without_parallel_model_call():
    _, credentials = _credentials()
    cfg = RunnerConfig(mock_mode=True, admin_credentials=credentials)
    service = JetsonRunnerService(cfg, identity=generate_identity("xavier-test"))
    service._admin_inference_lock.acquire()
    try:
        with pytest.raises(AdminRequestRejected) as exc:
            service.handle_admin_recognition(
                manifest=_manifest(),
                content_digest=multipart_content_sha256(_manifest()),
                image_paths={"front": "/tmp/front.jpg"},
                request_received_at="2026-07-14T00:00:00.000Z",
            )
    finally:
        service._admin_inference_lock.release()
    assert exc.value.code == "runner_busy"
    assert exc.value.http_status == 429


def test_admin_idempotency_key_rejects_changed_content():
    _, credentials = _credentials()
    cfg = RunnerConfig(mock_mode=True, admin_credentials=credentials)
    service = JetsonRunnerService(cfg, identity=generate_identity("xavier-test"))
    first = _manifest()
    service.handle_admin_recognition(
        manifest=first,
        content_digest=multipart_content_sha256(first),
        image_paths={"front": "/tmp/front.jpg"},
        request_received_at="2026-07-14T00:00:00.000Z",
    )
    changed = _manifest(b"changed")
    with pytest.raises(AdminRequestRejected) as exc:
        service.handle_admin_recognition(
            manifest=changed,
            content_digest=multipart_content_sha256(changed),
            image_paths={"front": "/tmp/front.jpg"},
            request_received_at="2026-07-14T00:00:01.000Z",
        )
    assert exc.value.code == "idempotency_conflict"
    assert exc.value.http_status == 409


def test_admin_recognition_cache_evicts_least_recently_used_response():
    _, credentials = _credentials()
    cfg = RunnerConfig(
        mock_mode=True,
        admin_credentials=credentials,
        recognition_cache_max_entries=2,
    )
    service = JetsonRunnerService(cfg, identity=generate_identity("xavier-test"))

    for request_id in ("adminrec-1", "adminrec-2", "adminrec-3"):
        manifest = _manifest()
        manifest["request_id"] = request_id
        service.handle_admin_recognition(
            manifest=manifest,
            content_digest=multipart_content_sha256(manifest),
            image_paths={"front": "/tmp/front.jpg"},
            request_received_at="2026-07-14T00:00:00.000Z",
        )

    assert service.get_admin_recognition("adminrec-1") is None
    assert service.get_admin_recognition("adminrec-2") is not None
    assert service.get_admin_recognition("adminrec-3") is not None


def test_admin_health_requires_authentication():
    _, client = _mock_client()
    response = client.get("/api/v2/admin-runner/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
