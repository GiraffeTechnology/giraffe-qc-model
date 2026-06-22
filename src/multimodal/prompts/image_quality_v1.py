"""Image quality assessment prompt — version 1."""
from __future__ import annotations

VERSION = "image-quality-v1"

SYSTEM_ROLE = (
    "You are a visual quality-control image-assessment engine. "
    "Your sole task is to determine whether the provided image is suitable for QC inspection."
)

SAFETY_RULES = (
    "Rules:\n"
    "- Do not invent defects. Only report what is visible.\n"
    "- If uncertain, set usable=false and recommended_action=manual_review.\n"
    "- Never return pass for a blurry, occluded, or angle-mismatched image.\n"
    "- Return JSON only. No markdown. No explanation outside the JSON."
)

OUTPUT_SCHEMA = """{\n  \"usable\": true,\n  \"confidence\": 0.95,\n  \"issues\": [{\"issue_type\": \"blur|low_light|overexposure|occlusion|wrong_angle|too_far|too_close|background_noise|unknown\", \"severity\": \"low|medium|high\", \"description\": \"...\"}],\n  \"recommended_action\": \"proceed|retake|manual_review\",\n  \"reason\": \"...\"\n}"""

def build_prompt(expected_angle: str | None = None) -> str:
    angle_hint = f"\nExpected camera angle: {expected_angle}." if expected_angle else ""
    return (
        f"{SYSTEM_ROLE}\n\n"
        f"Task: Assess whether the provided image is usable for QC inspection.{angle_hint}\n\n"
        f"{SAFETY_RULES}\n\n"
        f"Output schema (strict JSON):\n{OUTPUT_SCHEMA}"
    )
