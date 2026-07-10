"""Readiness resolver (§5) — fail-closed submit gate + contract validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.qc_model.jetson import constants as C
from src.qc_model.jetson import service
from src.qc_model.jetson.contract import validate_request
from src.qc_model.jetson.identity import derive_fingerprint, fingerprints_match


def test_readiness_precedence_no_sku_first():
    assert service.resolve_readiness(sku_selected=False, standard_installed=False, jetson_reachable=False) == C.NO_SKU


def test_readiness_no_standard():
    assert service.resolve_readiness(sku_selected=True, standard_installed=False, jetson_reachable=True) == C.NO_STANDARD


def test_readiness_unreachable_blocks_submission():
    state = service.resolve_readiness(sku_selected=True, standard_installed=True, jetson_reachable=False)
    assert state == C.UNREACHABLE
    assert service.can_submit_inspection(state) is False  # fail-closed


def test_readiness_connecting_when_model_not_loaded():
    state = service.resolve_readiness(sku_selected=True, standard_installed=True, jetson_reachable=True, service_up=True, model_loaded=False)
    assert state == C.CONNECTING
    assert service.can_submit_inspection(state) is False


def test_readiness_ready_allows_submission():
    state = service.resolve_readiness(sku_selected=True, standard_installed=True, jetson_reachable=True, service_up=True, model_loaded=True)
    assert state == C.READY
    assert service.can_submit_inspection(state) is True


def test_fingerprint_is_deterministic_and_matches():
    fp1 = derive_fingerprint("pubkey-abc")
    fp2 = derive_fingerprint("pubkey-abc")
    assert fp1 == fp2
    assert fingerprints_match(fp1, fp2.replace("-", " "))
    assert not fingerprints_match(fp1, derive_fingerprint("pubkey-xyz"))


def test_contract_rejects_empty_detection_points():
    with pytest.raises(ValidationError):
        validate_request({"job_id": "j", "standard_revision_id": "r", "image": "x", "detection_points": []})


def test_contract_accepts_valid_request():
    req = validate_request({
        "job_id": "j1", "standard_revision_id": "r1", "bundle_version": "1.0.0", "image": "frame://x",
        "detection_points": [{"point_code": "cp1", "label": "core centered", "regions": [{"image_id": "i1", "x": 1, "y": 2, "w": 3, "h": 4}]}],
    })
    assert req.job_id == "j1"
    assert req.detection_points[0].regions[0].w == 3
