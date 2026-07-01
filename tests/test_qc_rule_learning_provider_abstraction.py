"""Rule-learning provider abstraction tests (PRD §18.1)."""
from __future__ import annotations

import ast
from pathlib import Path

from tests.qc_learning_helpers import (
    OPERATOR_REQUIREMENT_TEXT,
    new_session,
    seed_sku,
)

from src.qc_model.learning import service
from src.qc_model.learning.providers.base import QCRuleLearningProvider
from src.qc_model.learning.providers.compat_provider import MainstreamRuleLearningAdapter
from src.qc_model.learning.providers.mock_provider import MockRuleLearningProvider
from src.qc_model.learning.schemas import LearningJobStatus, QCRuleLearningResponse


def _job_with_requirement(db):
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    return job


def test_phase1_readiness_api_still_importable_from_package():
    """The Phase 1 learning-readiness API must survive the package migration."""
    from src.qc_model.learning import (
        LearningReadiness,
        advance_to_exam_ready,
        evaluate_learning_readiness,
    )

    assert LearningReadiness is not None
    assert callable(evaluate_learning_readiness)
    assert callable(advance_to_exam_ready)


def test_mock_provider_satisfies_interface():
    assert isinstance(MockRuleLearningProvider(), QCRuleLearningProvider)


def test_mainstream_stub_satisfies_interface():
    adapter = MainstreamRuleLearningAdapter(
        lambda req: QCRuleLearningResponse(provider="x", model="y"),
        provider_name="mainstream_x",
    )
    assert isinstance(adapter, QCRuleLearningProvider)


def test_product_learning_logic_depends_on_abstraction_not_qwen():
    """Product learning modules must not import the concrete Qwen class."""
    product_modules = [
        "src/qc_model/learning/service.py",
        "src/qc_model/learning/apply.py",
        "src/qc_model/learning/validator.py",
        "src/qc_model/learning/report.py",
        "src/qc_model/learning/runtime_policy.py",
    ]
    for rel in product_modules:
        tree = ast.parse(Path(rel).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                names.extend(alias.name for alias in node.names)
                for name in names:
                    assert "qwen3_5_vl" not in name and "Qwen35VL" not in name, (
                        f"{rel} imports Qwen-specific symbol {name!r}"
                    )


def test_provider_failure_marks_job_failed_and_requires_review():
    db = new_session()
    job = _job_with_requirement(db)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider(valid=False))
    assert job.status == LearningJobStatus.FAILED.value
    report = service.get_report(db, job.id)
    assert report["requires_supervisor_review"] is True
    assert report["can_apply_to_training_pack"] is False
    # No proposals should have been created.
    assert service.list_detection_point_proposals(db, job.id) == []


def test_provider_exception_is_caught_and_fails_closed():
    class BoomProvider(MockRuleLearningProvider):
        def learn_rules(self, request):
            raise RuntimeError("backend down")

    db = new_session()
    job = _job_with_requirement(db)
    job = service.run_learning(db, job.id, provider=BoomProvider())
    assert job.status == LearningJobStatus.FAILED.value


def test_mainstream_stub_can_drive_a_job():
    from src.qc_model.learning.requirement_structuring import structure_requirements
    from src.qc_model.learning.schemas import LearnedDetectionPointProposal

    def call_fn(req):
        proposals = [
            LearnedDetectionPointProposal(
                proposal_id=f"p{i}",
                learning_job_id=req.learning_job_id,
                **item,
            )
            for i, item in enumerate(structure_requirements(req.operator_requirements))
        ]
        return QCRuleLearningResponse(
            provider="mainstream_x",
            model="vendor-x",
            runtime_profile=req.runtime_profile,
            detection_point_proposals=proposals,
        )

    db = new_session()
    job = _job_with_requirement(db)
    job = service.run_learning(
        db, job.id, provider=MainstreamRuleLearningAdapter(call_fn, provider_name="mainstream_x")
    )
    assert job.status == LearningJobStatus.PROPOSED.value
    assert job.provider == "mainstream_x"
