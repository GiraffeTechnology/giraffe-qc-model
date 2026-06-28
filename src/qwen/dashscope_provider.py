"""DashScope cloud QWEN provider for QC inspection.

Requires both QWEN_CLOUD_ENABLED=true AND ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true
to be set before making any API calls.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import List

import httpx

from src.qwen.base import QwenQCProvider
from src.qwen.parser import parse_qwen_output
from src.qwen.prompt_builder import build_prompt
from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    QwenInspectionOutput,
    StandardPhotoInput,
)

_DASHSCOPE_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
_DEFAULT_MODEL = "qwen-vl-max"
ENGINE_NAME = "cloud_qwen"


def _cloud_enabled() -> bool:
    return os.getenv("QWEN_CLOUD_ENABLED", "false").lower() == "true"


def _images_allowed() -> bool:
    return os.getenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "false").lower() == "true"


def _encode_image_base64(path: str) -> str:
    """Encode an image file as base64."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _require_readable_image(path: str, label: str) -> None:
    if not path:
        raise RuntimeError(f"{label} local_path is required")
    image_path = Path(path)
    if not image_path.is_file():
        raise RuntimeError(f"{label} is missing or not a file: {path}")
    try:
        with image_path.open("rb") as f:
            f.read(1)
    except OSError as exc:
        raise RuntimeError(f"{label} is unreadable: {path}") from exc


class DashScopeQwenProvider(QwenQCProvider):
    """QC provider that calls the DashScope QWEN-VL cloud API.

    Safety checks:
    - QWEN_CLOUD_ENABLED must be "true"
    - ALLOW_SEND_IMAGES_TO_CLOUD_QWEN must be "true"
    Both guards must pass before any image is sent to the cloud.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
        self._model = model
        self._timeout = timeout

    @property
    def engine_name(self) -> str:
        return ENGINE_NAME

    def _check_guards(self) -> None:
        """Check all safety guards before making API calls."""
        if not _cloud_enabled():
            raise RuntimeError(
                "QWEN cloud disabled: set QWEN_CLOUD_ENABLED=true to enable"
            )
        if not _images_allowed():
            raise RuntimeError(
                "Sending images to cloud QWEN is disabled: "
                "set ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true to allow"
            )
        if not self._api_key:
            raise RuntimeError(
                "No DashScope API key found. Set DASHSCOPE_API_KEY or QWEN_API_KEY env var."
            )

    def inspect(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        """Run QC inspection via DashScope QWEN-VL API."""
        self._check_guards()

        if not standard_photos:
            raise RuntimeError("No standard photos supplied; inspection requires reference inputs")
        if not qc_points:
            raise RuntimeError("No QC detection points supplied; inspection requires detection points")
        for photo in standard_photos:
            _require_readable_image(photo.local_path, f"Standard photo {photo.photo_id}")
        _require_readable_image(captured_photo.local_path, f"Capture photo {captured_photo.photo_id}")

        expected_ids = [p.qc_point_id for p in qc_points]

        # Build output schema for the prompt
        schema_example = {
            "overall_result": "pass | fail | review_required",
            "confidence": 0.95,
            "model_name": self._model,
            "summary": "Overall inspection summary",
            "items": [
                {
                    "qc_point_id": "<id>",
                    "qc_point_code": "<code>",
                    "name": "<name>",
                    "result": "pass | fail | review_required",
                    "confidence": 0.9,
                    "reason": "<reason>",
                    "evidence": {},
                }
            ],
        }
        schema_json = json.dumps(schema_example, indent=2)
        prompt_text = build_prompt(standard_photos, captured_photo, qc_points, schema_json)

        # Build multimodal message content
        content = []

        # Add standard photos as images
        for photo in standard_photos:
            img_b64 = _encode_image_base64(photo.local_path)
            # Detect MIME type from extension
            ext = Path(photo.local_path).suffix.lower()
            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
            content.append({
                "image": f"data:{mime};base64,{img_b64}"
            })

        # Add capture photo
        cap_b64 = _encode_image_base64(captured_photo.local_path)
        ext = Path(captured_photo.local_path).suffix.lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        content.append({"image": f"data:{mime};base64,{cap_b64}"})

        content.append({"text": prompt_text})

        payload = {
            "model": self._model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": {
                "result_format": "message",
            },
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        response = httpx.post(
            _DASHSCOPE_API_URL,
            json=payload,
            headers=headers,
            timeout=self._timeout,
        )
        response.raise_for_status()

        resp_data = response.json()
        raw_text = (
            resp_data.get("output", {})
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", [{}])[0]
            .get("text", "")
        )

        result = parse_qwen_output(raw_text, expected_ids, ENGINE_NAME)
        result = result.model_copy(update={"model_name": self._model})
        return result
