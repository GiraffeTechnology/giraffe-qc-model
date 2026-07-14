"""Configurable sandbox-only VLM client; never imported by production code."""
from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from sandbox_tests.common import SandboxConfig
from src.qc_model.production.provider import parse_provider_response


class SandboxInferenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxModelResponse:
    raw_output: str
    parser_input: str


class SandboxVLMClient:
    def __init__(self, config: SandboxConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        self._client = httpx.Client(
            timeout=config.timeout_seconds,
            headers=headers,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def infer(
        self, *, case: dict[str, Any], image_path: Path, cv_result: dict[str, Any]
    ) -> SandboxModelResponse:
        image_bytes = image_path.read_bytes()
        if len(image_bytes) > self.config.max_image_bytes:
            raise SandboxInferenceError("input_image_exceeds_configured_limit")
        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        prompt = _prompt(case, cv_result)
        if self.config.api_style == "openai_chat":
            payload = {
                "model": self.config.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                "temperature": 0,
                "max_tokens": self.config.max_tokens,
            }
        else:
            payload = {
                "model": self.config.model,
                "detection_point_code": case["qc_point_id"],
                "checkpoint_category": case["category"],
                "confirmed_content": {
                    "criterion": case["criterion"],
                    "expected_behavior": case["expected_behavior"],
                    "cv_preanalysis": cv_result,
                },
                "image_data_url": data_url,
                "prompt_schema_version": "sandbox-stage1-v1",
            }
        try:
            response = self._client.post(
                self.config.server + self.config.inference_path,
                json=payload,
            )
            response.raise_for_status()
            raw_http_body = response.text
            body = response.json()
        except httpx.TimeoutException as exc:
            raise SandboxInferenceError("model_timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SandboxInferenceError(f"model_transport_or_decode_error:{type(exc).__name__}") from exc
        if self.config.api_style == "openai_chat":
            try:
                content = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise SandboxInferenceError("model_response_envelope_invalid") from exc
            if isinstance(content, list):
                content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
            if not isinstance(content, str):
                raise SandboxInferenceError("model_content_not_text")
            if len(content) > self.config.max_output_chars:
                raise SandboxInferenceError("model_content_exceeds_configured_limit")
            return SandboxModelResponse(raw_output=content, parser_input=content)
        if len(raw_http_body) > self.config.max_output_chars:
            raise SandboxInferenceError("model_content_exceeds_configured_limit")
        try:
            parsed = parse_provider_response(body)
        except ValueError as exc:
            raise SandboxInferenceError("inspection_response_schema_invalid") from exc
        item_result = {
            "pass_recommended": "pass",
            "reject_recommended": "fail",
        }.get(parsed.disposition, "review_required")
        parser_value = {
            "overall_result": item_result,
            "confidence": parsed.confidence,
            "model_name": parsed.model or self.config.model,
            "summary": parsed.uncertainty,
            "items": [
                {
                    "qc_point_id": case["qc_point_id"],
                    "qc_point_code": case["qc_point_id"],
                    "name": case["name"],
                    "result": item_result,
                    "confidence": parsed.confidence,
                    "reason": json.dumps(
                        {
                            "observed_features": parsed.observed_features,
                            "defect_features": parsed.defect_features,
                            "uncertainty": parsed.uncertainty,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "evidence": {"regions": parsed.evidence_regions},
                }
            ],
        }
        return SandboxModelResponse(
            raw_output=raw_http_body,
            parser_input=json.dumps(parser_value, ensure_ascii=False, separators=(",", ":")),
        )


def _prompt(case: dict[str, Any], cv_result: dict[str, Any]) -> str:
    schema = {
        "overall_result": "pass|fail|review_required",
        "confidence": "0..1",
        "model_name": "configured model identity",
        "summary": "short evidence summary",
        "items": [
            {
                "qc_point_id": case["qc_point_id"],
                "qc_point_code": case["qc_point_id"],
                "name": case["name"],
                "result": "pass|fail|review_required",
                "confidence": "0..1",
                "reason": "visual evidence",
                "evidence": {},
            }
        ],
    }
    parser_probe = (
        "For the Stage 1 parser probe, use a brief native reasoning trace "
        "before the final JSON object. "
        if case.get("require_think_wrapper")
        else ""
    )
    return (
        "SANDBOX CHAIN-VALIDATION REQUEST. Inspect exactly one QC point. "
        "Return one JSON object only; do not add prose after it.\n"
        f"Category: {case['category']}\nCriterion: {case['criterion']}\n"
        f"Expected behavior: {case['expected_behavior']}\n"
        "<CV_PREANALYSIS_JSON>\n"
        + json.dumps(cv_result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n</CV_PREANALYSIS_JSON>\n"
        "CV evidence is informational only. If evidence is insufficient, use review_required.\n"
        + parser_probe
        + "Required output schema:\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
