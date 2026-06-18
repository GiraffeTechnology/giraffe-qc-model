"""Versioned prompt builder for the QWEN QC inspection pipeline.

Prompt version: qwen-qc-v1
"""
from __future__ import annotations

import json
from typing import List

from src.qwen.schema import StandardPhotoInput, CapturePhotoInput, QcPointInput

PROMPT_VERSION = "qwen-qc-v1"

_PROMPT_TEMPLATE = """\
You are a professional product quality control (QC) inspector. Your task is to inspect a production product photo against reference standard photos and a set of QC criteria.

## Standard (Reference) Photos
{standard_photos_desc}

## Captured Production Photo
{capture_photo_desc}

## QC Inspection Points
{qc_points_desc}

## Instructions
1. Carefully compare the captured production photo against the standard reference photos.
2. For each QC inspection point listed above, determine whether it passes, fails, or requires manual review.
3. Provide a confidence score between 0.0 and 1.0 for each determination.
4. Give a clear reason for each determination.
5. Provide an overall result for the entire inspection.

## Output Format
Respond ONLY with a valid JSON object matching this schema exactly:
{schema_json}

Important rules:
- Only include the QC point IDs listed above in "items". Do not hallucinate new IDs.
- The "overall_result" must be "pass" only if ALL items pass. If any item fails, overall is "fail". If uncertain, use "review_required".
- Confidence values must be between 0.0 and 1.0.
- Do not include any text outside the JSON object.
"""


def build_prompt(
    standard_photos: List[StandardPhotoInput],
    captured_photo: CapturePhotoInput,
    qc_points: List[QcPointInput],
    schema_json: str,
) -> str:
    """Build the QC inspection prompt.

    Args:
        standard_photos: List of standard reference photo inputs
        captured_photo: The captured production photo input
        qc_points: List of QC inspection points to evaluate
        schema_json: JSON schema string for the expected output format

    Returns:
        Formatted prompt string (version: qwen-qc-v1)
    """
    # Build standard photos description
    if standard_photos:
        photos_parts = []
        for i, photo in enumerate(standard_photos, 1):
            angle_str = f" (angle: {photo.angle})" if photo.angle else ""
            photos_parts.append(f"{i}. Photo ID: {photo.photo_id}{angle_str} — {photo.local_path}")
        standard_photos_desc = "\n".join(photos_parts)
    else:
        standard_photos_desc = "(No standard photos provided)"

    # Build capture photo description
    capture_photo_desc = f"Photo ID: {captured_photo.photo_id} — {captured_photo.local_path}"

    # Build QC points description
    if qc_points:
        points_parts = []
        for i, point in enumerate(qc_points, 1):
            rule_str = f" [rule_type: {point.rule_type}]" if point.rule_type else ""
            roi_str = f" [roi: {json.dumps(point.roi_json)}]" if point.roi_json else ""
            points_parts.append(
                f"{i}. ID: {point.qc_point_id} | Code: {point.qc_point_code} | "
                f"Name: {point.name}{rule_str}{roi_str}\n"
                f"   Description: {point.description}"
            )
        qc_points_desc = "\n".join(points_parts)
    else:
        qc_points_desc = "(No QC points defined)"

    return _PROMPT_TEMPLATE.format(
        standard_photos_desc=standard_photos_desc,
        capture_photo_desc=capture_photo_desc,
        qc_points_desc=qc_points_desc,
        schema_json=schema_json,
    )
