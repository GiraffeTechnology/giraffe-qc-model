"""Prompt templates (PRD §15).

Templates, not ad-hoc hardcoded prompts. The system prompt names both default
runtime profiles. The inspection prompt is assembled from the confirmed
Training Pack context.
"""
from __future__ import annotations

from src.qc_model.providers.base import VisualInspectionRequest

SYSTEM_PROMPT_TEMPLATE = (
    "You are a digital visual QC inspector.\n"
    "The product default runtime profiles are qwen3.5-vl-2b-mnn for tablet / "
    "Pad MNN and qwen3.5-vl-8b-int4 for server.\n"
    "You inspect only the confirmed SKU and confirmed detection points.\n"
    "You do not guess missing standards.\n"
    "You distinguish true defects from normal material behavior and capture "
    "artifacts.\n"
    "You return review_required when uncertain.\n"
    "You output JSON only.\n"
)

BOUNDARY_PROMPT_TEMPLATE = (
    "Determine whether this visual anomaly is:\n"
    "1. true defect\n"
    "2. normal material behavior\n"
    "3. capture artifact\n"
    "4. uncertain\n"
)

EVIDENCE_PROMPT_TEMPLATE = (
    "Describe:\n"
    "- where the evidence is\n"
    "- what visual signal was observed\n"
    "- why it supports pass/fail/review_required\n"
    "- what alternative explanations were considered\n"
)


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE


def build_inspection_prompt(request: VisualInspectionRequest) -> str:
    """Assemble the inspection prompt from confirmed context (PRD §15.2)."""
    lines: list[str] = []
    lines.append(f"SKU identity: {request.sku_id}")
    lines.append(f"Station identity: {request.station_id}")
    lines.append(f"Capture protocol: {request.capture_protocol}")
    if request.reference_descriptions:
        lines.append("Reference image description:")
        for desc in request.reference_descriptions:
            lines.append(f"  - {desc}")
    lines.append("Confirmed detection points:")
    for dp in request.detection_points:
        lines.append(f"  - code={dp.get('code')} category={dp.get('checkpoint_category')}")
        if dp.get("normal_visual_features"):
            lines.append(f"    normal_visual_features: {dp['normal_visual_features']}")
        if dp.get("defect_visual_features"):
            lines.append(f"    defect_visual_features: {dp['defect_visual_features']}")
        if dp.get("known_pseudo_defects"):
            lines.append(f"    known_pseudo_defects: {dp['known_pseudo_defects']}")
        if dp.get("decision_rule"):
            lines.append(f"    decision_rule: {dp['decision_rule']}")
        if dp.get("review_required_conditions"):
            lines.append(f"    review_required_conditions: {dp['review_required_conditions']}")
    lines.append("")
    lines.append(EVIDENCE_PROMPT_TEMPLATE)
    lines.append("Return structured JSON only, matching the provided schema.")
    return "\n".join(lines)
