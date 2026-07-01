"""Deterministic mock rule-learning provider for Phase 2A tests.

Produces structured proposals from operator requirements using the
deterministic requirement structurer. A passing mock test proves the learning
*workflow* and safety gates work — it does NOT prove real qwen3.5-vl visual
accuracy (PRD §3, §19).
"""
from __future__ import annotations

import uuid

from src.qc_model.learning.providers.base import QCRuleLearningProvider
from src.qc_model.learning.requirement_structuring import structure_requirements
from src.qc_model.learning.schemas import (
    LearnedDetectionPointProposal,
    LearnedVisualRuleProposal,
    QCRuleLearningRequest,
    QCRuleLearningResponse,
    RuleType,
)
from src.qc_model.schemas.checkpoint import CheckpointCategory


def _uid() -> str:
    return uuid.uuid4().hex


class MockRuleLearningProvider(QCRuleLearningProvider):
    """Scriptable deterministic mock.

    ``valid=False`` simulates an unparseable/failed provider so the service
    fails the job closed.
    """

    def __init__(
        self,
        provider_name: str = "mock_rule_learning",
        model_name: str = "mock-rule-learning-v1",
        valid: bool = True,
    ) -> None:
        self._provider_name = provider_name
        self._model_name = model_name
        self._valid = valid

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def learn_rules(self, request: QCRuleLearningRequest) -> QCRuleLearningResponse:
        if not self._valid:
            return QCRuleLearningResponse(
                provider=self._provider_name,
                model=self._model_name,
                runtime_profile=request.runtime_profile,
                valid=False,
                error="mock: unparseable / failed learning output",
            )

        structured = structure_requirements(request.operator_requirements)
        dp_proposals: list[LearnedDetectionPointProposal] = []
        rule_proposals: list[LearnedVisualRuleProposal] = []
        physical_warnings: list[str] = []

        # All defect/boundary sample refs are available as rule evidence.
        sample_evidence = (
            list(request.sample_refs.defect_samples)
            + list(request.sample_refs.boundary_samples)
        )

        for item in structured:
            proposal_id = _uid()
            dp_proposals.append(
                LearnedDetectionPointProposal(
                    proposal_id=proposal_id,
                    learning_job_id=request.learning_job_id,
                    requires_supervisor_confirmation=True,
                    **item,
                )
            )

            if item["proposed_checkpoint_category"] == CheckpointCategory.PHYSICAL_MEASUREMENT.value:
                physical_warnings.append(
                    f"{item['proposed_code']}: physical measurement — AI is record_only, "
                    "operator must measure with fixture/ruler/gauge."
                )

            # Emit visual rule proposals tied to this detection point proposal.
            rule_proposals.extend(
                self._rules_for(request, proposal_id, item, sample_evidence)
            )

        return QCRuleLearningResponse(
            provider=self._provider_name,
            model=self._model_name,
            runtime_profile=request.runtime_profile,
            detection_point_proposals=dp_proposals,
            visual_rule_proposals=rule_proposals,
            physical_measurement_warnings=physical_warnings,
            open_questions=[],
            uncertainties=[],
            valid=True,
        )

    def _rules_for(self, request, proposal_id, item, sample_evidence):
        rules: list[LearnedVisualRuleProposal] = []

        def _rule(rule_type: RuleType, text: str, samples: list[str]):
            rules.append(
                LearnedVisualRuleProposal(
                    rule_id=_uid(),
                    learning_job_id=request.learning_job_id,
                    detection_point_proposal_id=proposal_id,
                    rule_type=rule_type,
                    rule_text=text,
                    source_samples=samples,
                    source_requirement=item.get("source_requirement", ""),
                    provider=self._provider_name,
                    model=self._model_name,
                    runtime_profile=request.runtime_profile,
                    confidence=0.7,
                    requires_supervisor_confirmation=True,
                )
            )

        for feat in item.get("normal_visual_features", []):
            _rule(RuleType.NORMAL_FEATURE, feat, list(request.sample_refs.positive_samples))
        for feat in item.get("defect_visual_features", []):
            _rule(RuleType.DEFECT_FEATURE, feat, sample_evidence)
        for pseudo in item.get("known_pseudo_defects", []):
            _rule(RuleType.PSEUDO_DEFECT, pseudo, list(request.sample_refs.boundary_samples))
        if item.get("decision_rule"):
            _rule(RuleType.DECISION_RULE, item["decision_rule"], [])
        for cond in item.get("review_required_conditions", []):
            _rule(RuleType.REVIEW_REQUIRED_CONDITION, cond, [])
        return rules
