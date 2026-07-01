"""Learning workflow skeleton (PRD §12).

Phase 1 implements structure and state transitions only. It does NOT prove
real model learning quality. The key guardrail enforced here: a Training Pack
cannot become ``exam_ready`` while the Playbook comprehension has open
questions/ambiguities.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.qc_model.schemas.training_pack import TrainingPack, TrainingPackStatus


@dataclass
class LearningReadiness:
    ready_for_exam: bool
    blockers: list[str] = field(default_factory=list)


def evaluate_learning_readiness(pack: TrainingPack) -> LearningReadiness:
    """Decide whether a Training Pack may advance to ``exam_ready``."""
    blockers: list[str] = []

    blockers.extend(pack.missing_requirements())

    if pack.playbook is None:
        blockers.append("missing_playbook")
    elif pack.playbook.has_open_questions():
        blockers.append("playbook_has_open_questions")

    if not pack.defect_samples and not pack.boundary_samples:
        # Without any defect/boundary material the model cannot be examined
        # meaningfully — allow learning but not exam readiness.
        blockers.append("insufficient_defect_or_boundary_samples")

    # de-dup while preserving order
    seen: set[str] = set()
    unique_blockers = [b for b in blockers if not (b in seen or seen.add(b))]
    return LearningReadiness(ready_for_exam=not unique_blockers, blockers=unique_blockers)


def advance_to_exam_ready(pack: TrainingPack) -> TrainingPack:
    """Advance a pack to ``exam_ready`` if and only if it is ready."""
    readiness = evaluate_learning_readiness(pack)
    if not readiness.ready_for_exam:
        raise ValueError(
            f"Training Pack {pack.training_pack_id} not ready for exam: "
            f"{', '.join(readiness.blockers)}"
        )
    return pack.model_copy(update={"status": TrainingPackStatus.EXAM_READY})
