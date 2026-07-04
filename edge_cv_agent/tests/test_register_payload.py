"""Registration + heartbeat payload builders (§8.1, §8.2)."""
from edge_cv_agent.app.config import AgentConfig
from edge_cv_agent.app.device_register import build_register_payload
from edge_cv_agent.app.heartbeat import build_heartbeat_payload
from edge_cv_agent.app.result_uploader import build_result_payload
from edge_cv_agent.app.cv_pipeline import run_mock_pipeline


def test_register_payload_shape():
    cfg = AgentConfig(device_name="jetson-nano-2gb-lab-001", device_type="jetson_nano_2gb")
    payload = build_register_payload(cfg)
    assert payload["device_name"] == "jetson-nano-2gb-lab-001"
    assert payload["device_type"] == "jetson_nano_2gb"
    assert "defect_candidate_detection" in payload["capabilities"]
    assert "live_candidate_lock_capture" in payload["capabilities"]
    assert payload["max_concurrent_jobs"] == 1
    assert payload["runtime"]["opencv"] is True


def test_heartbeat_payload_has_metrics():
    payload = build_heartbeat_payload("edge_dev_1", "edge_sess_1", mock=True, active_job_count=1)
    assert payload["device_id"] == "edge_dev_1"
    assert payload["active_job_count"] == 1
    assert payload["metrics"]["memory_total_mb"] == 2048.0


def test_result_payload_carries_model_hash():
    out = run_mock_pipeline({"cv_job_id": "j", "input_payload": {}})
    payload = build_result_payload("edge_dev_1", "edge_sess_1", out, model_id="m1", model_hash="mock-hash")
    assert payload["model_hash"] == "mock-hash"
    assert payload["result_type"] == "detection"
    assert payload["pass_fail_hint"] == "needs_human_review"
