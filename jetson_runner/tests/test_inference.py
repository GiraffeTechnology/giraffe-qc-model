"""Mock qc-model inference behaviour + §4 contract handling."""
import pytest
from pydantic import ValidationError

from jetson_runner.app import inference_server
from jetson_runner.app.config import RunnerConfig
from jetson_runner.app.identity import generate_identity
from jetson_runner.app.main import JetsonRunnerService


def _req(points):
    return {"job_id": "j1", "standard_revision_id": "r1", "image": "x", "detection_points": points}


def test_inference_returns_result_per_point():
    resp = inference_server.run_inference(_req([{"point_code": "cp1"}, {"point_code": "cp2"}]))
    assert resp["job_id"] == "j1"
    assert {r["point_code"] for r in resp["per_point_results"]} == {"cp1", "cp2"}
    for r in resp["per_point_results"]:
        assert r["result"] in ("pass", "fail", "uncertain")


def test_mock_result_hint_is_honored():
    resp = inference_server.run_inference(_req([{"point_code": "cp1", "mock_result": "fail"}]))
    assert resp["per_point_results"][0]["result"] == "fail"


def test_malformed_request_raises():
    with pytest.raises(ValidationError):
        inference_server.run_inference(_req([]))  # empty detection points


def test_health_report_shape():
    svc = JetsonRunnerService(RunnerConfig(mock_mode=True), identity=generate_identity("jetson-test"))
    report = svc.health_report()
    assert report["service_up"] is True
    assert report["readiness_state"] == "jetson_ready"
    assert report["jetson_device_id"] == "jetson-test"


def test_provisioning_identity_and_chassis_label():
    ident = generate_identity("jetson-xyz")
    assert ident.jetson_device_id == "jetson-xyz"
    assert ident.fingerprint.count("-") == 3  # NNNN-NNNN-NNNN-NNNN
    assert ident.jetson_device_id in ident.chassis_label
    assert ident.fingerprint in ident.chassis_label
