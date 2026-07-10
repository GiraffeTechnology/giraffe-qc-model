"""Headless pairing + fail-closed inference auth (no hardware, no network)."""
import itertools

import pytest

from jetson_runner.app.config import RunnerConfig
from jetson_runner.app.identity import generate_identity
from jetson_runner.app.main import InferenceRejected, JetsonRunnerService
from jetson_runner.app.pad_client import MockPad
from jetson_runner.app.pairing_agent import PairingAgent, PairingRejected


def _service():
    return JetsonRunnerService(RunnerConfig(mock_mode=True), identity=generate_identity("jetson-test"))


def _request(job="j1"):
    return {
        "job_id": job, "standard_revision_id": "r1", "bundle_version": "1.0.0", "image": "frame://x",
        "detection_points": [{"point_code": "cp1", "label": "core centered", "mock_result": "pass"}],
    }


def test_usb_pairing_then_signed_inference_ok():
    svc = _service()
    pad = MockPad("pad-1")
    pad.pair_over_usb(svc.pairing)
    resp = pad.call(svc, _request())
    assert resp["per_point_results"][0]["result"] == "pass"


def test_unpaired_caller_rejected():
    svc = _service()
    # An unpaired caller has no per-pair key; the service rejects on identity
    # before any signature check.
    with pytest.raises(InferenceRejected) as exc:
        svc.handle_inference(pad_device_id="pad-unknown", signature="whatever", payload=_request())
    assert exc.value.reason == "unpaired_caller"


def test_wifi_pairing_requires_open_window():
    svc = _service()
    pad = MockPad("pad-1")
    # Window closed → rejected outright.
    with pytest.raises(PairingRejected) as exc:
        pad.pair_over_wifi(svc.pairing, svc.identity.fingerprint)
    assert exc.value.args[0] == "pairing_window_closed"


def test_wifi_pairing_within_window_with_fingerprint():
    svc = _service()
    pad = MockPad("pad-1")
    svc.pairing.open_pairing_window(seconds=120)
    pad.pair_over_wifi(svc.pairing, svc.identity.fingerprint)
    assert pad.call(svc, _request())["job_id"] == "j1"


def test_wifi_pairing_wrong_fingerprint_rejected():
    svc = _service()
    pad = MockPad("pad-1")
    svc.pairing.open_pairing_window(seconds=120)
    with pytest.raises(PairingRejected) as exc:
        pad.pair_over_wifi(svc.pairing, "0000-0000-0000-0000")
    assert exc.value.args[0] == "fingerprint_mismatch"


def test_wifi_window_expires():
    ticks = itertools.chain([0.0], itertools.repeat(1000.0))
    agent = PairingAgent(generate_identity("jetson-test"), clock=lambda: next(ticks))
    agent.open_pairing_window(seconds=120)  # opened at t=0 → expires at 120
    # Next clock read is 1000 → window closed.
    with pytest.raises(PairingRejected):
        agent.pair_wifi("pad-1", "pub", agent.identity.fingerprint)


def test_repair_fail_closed_old_pad_rejected_no_grace():
    svc = _service()
    old = MockPad("pad-OLD")
    old.pair_over_usb(svc.pairing)
    assert old.call(svc, _request())["job_id"] == "j1"  # works while paired

    # A new Pad pairs → replaces the binding immediately.
    new = MockPad("pad-NEW")
    new.pair_over_usb(svc.pairing)
    assert new.call(svc, _request("j2"))["job_id"] == "j2"

    # Old Pad's signed request is now rejected with no grace period.
    with pytest.raises(InferenceRejected) as exc:
        old.call(svc, _request("j3"))
    assert exc.value.reason == "unpaired_caller"


def test_bad_signature_rejected():
    svc = _service()
    pad = MockPad("pad-1")
    pad.pair_over_usb(svc.pairing)
    with pytest.raises(InferenceRejected) as exc:
        svc.handle_inference(pad_device_id="pad-1", signature="deadbeef", payload=_request())
    assert exc.value.reason == "bad_signature"


def test_tampered_payload_rejected():
    svc = _service()
    pad = MockPad("pad-1")
    pad.pair_over_usb(svc.pairing)
    env = pad.signed_inference(_request())
    env["request"]["job_id"] = "tampered"  # change payload after signing
    with pytest.raises(InferenceRejected) as exc:
        svc.handle_inference(pad_device_id="pad-1", signature=env["signature"], payload=env["request"])
    assert exc.value.reason == "bad_signature"
