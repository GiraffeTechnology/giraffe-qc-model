"""Runtime profile policy tests for learning (PRD §4, §18.6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.qc_learning_helpers import new_session, seed_sku

from src.qc_model.learning import service
from src.qc_model.learning.providers.mock_provider import MockRuleLearningProvider
from src.qc_model.learning.runtime_policy import (
    DEFAULT_LEARNING_ENVIRONMENT,
    LearningRuntimeError,
    evaluate_learning_runtime,
    resolve_learning_profile,
)
from src.qc_model.learning.schemas import LearningJobStatus


def test_default_learning_runtime_is_server():
    assert DEFAULT_LEARNING_ENVIRONMENT.value == "server"
    profile = resolve_learning_profile()
    assert profile.environment.value == "server"


def test_default_learning_model_is_8b_int4():
    assert resolve_learning_profile().model == "qwen3.5-vl-8b-int4"


def test_server_runtime_is_allowed():
    decision = evaluate_learning_runtime("server")
    assert decision.allowed is True
    assert decision.profile.model == "qwen3.5-vl-8b-int4"


def test_tablet_mnn_not_used_by_default_for_learning():
    # The default resolution never yields tablet.
    assert resolve_learning_profile().environment.value != "tablet_mnn"
    # Explicitly requesting tablet is not allowed for learning.
    decision = evaluate_learning_runtime("tablet_mnn")
    assert decision.allowed is False
    assert "tablet_mnn_not_allowed_for_learning" in decision.reason


def test_tablet_mnn_learning_attempt_is_rejected_and_requires_review():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, "Check petal cracks")
    job = service.run_learning(
        db, job.id, requested_runtime="tablet_mnn", provider=MockRuleLearningProvider()
    )
    assert job.status == LearningJobStatus.FAILED.value
    assert "tablet_mnn_not_allowed_for_learning" in job.error_message
    report = service.get_report(db, job.id)
    assert report["requires_supervisor_review"] is True
    # No proposals were created from a tablet learning attempt.
    assert service.list_detection_point_proposals(db, job.id) == []


def test_desktop_pc_mnn_is_forbidden():
    with pytest.raises(LearningRuntimeError):
        resolve_learning_profile("desktop_pc_mnn")
    decision = evaluate_learning_runtime("desktop_pc_mnn")
    assert decision.allowed is False
    assert decision.reason == "forbidden_or_unknown_runtime"


def test_desktop_pc_mnn_string_absent_from_learning_source_tree():
    learning_dir = Path("src/qc_model/learning")
    for path in learning_dir.rglob("*.py"):
        text = path.read_text()
        assert "desktop_pc_mnn" not in text or "forbidden" in text.lower() or "FORBIDDEN" in text, (
            f"{path} references desktop_pc_mnn outside a forbidden-guard context"
        )
