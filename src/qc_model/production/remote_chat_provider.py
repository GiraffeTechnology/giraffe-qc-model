"""Remote OpenAI-compatible chat VLM inspection provider (Stage 3 Group B).

Group B (docs/STAGE3_AB_TESTING_SPEC.md §2) screens with Jetson-local CV plus
a *remote* VLM reached only through ``/v1/chat/completions`` — the contract a
self-hosted MNN chat server exposes, not the repo's ``/v1/inspect`` contract
that :class:`~src.qc_model.production.provider.ServerVLMInspectionProvider`
speaks. This module is the adapter side of GAP-06: it builds a strict prompt
and an OpenAI-compatible vision chat request, then parses the response back
into the same :class:`DetectionInspectionResult` schema so downstream code
cannot tell which wire protocol produced a recommendation.

Fail-closed, matching the existing provider: unconfigured, unreachable,
timed-out, or malformed-JSON responses all raise — never a silent fallback to
mock, another provider, or a guessed result.

Configuration (env, per docs/STAGE3_AB_TESTING_SPEC.md §Group B):

* ``VLM_BASE_URL`` — base URL of the remote chat endpoint. In production this
  must be a loopback address reached through the restricted SSH/TLS tunnel
  described in ``docs/STAGE3_GROUP_B_REMOTE_ADAPTER.md`` — never expose the
  remote inference port directly to a public interface.
* ``VLM_MODEL`` — the remote model's configured name/alias.
* ``VLM_API_KEY`` — optional bearer token, if the tunnel endpoint requires one.
* ``VLM_TIMEOUT_SECONDS`` — request timeout (default 30s).
* ``VLM_MAX_IMAGE_BYTES`` — local image size cap before refusing to embed it
  (default 5 MiB) — bounds the request payload and gives an explicit,
  auditable limit rather than an implicit one.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
from pathlib import Path

from src.qc_model.production.provider import (
    PROMPT_SCHEMA_VERSION,
    DetectionInspectionRequest,
    DetectionInspectionResult,
    ProductionInspectionProvider,
    ProductionProviderError,
    ProductionProviderNotConfigured,
    ProductionProviderSchemaError,
    parse_provider_response,
)

_JSON_FENCE_START = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_JSON_FENCE_END = re.compile(r"\s*```$")

_RESPONSE_SCHEMA_EXAMPLE = {
    "detection_point_code": "<echo the provided detection_point_code exactly>",
    "disposition": "pass_recommended | fail_recommended | review_required",
    "observed_features": ["<visible feature strings>"],
    "defect_features": [],
    "normal_features_matched": [],
    "evidence_regions": [{"bbox": None, "note": "<optional>"}],
    "confidence": 0.0,
    "uncertainty": "<empty string if none>",
    "review_required_conditions": [],
    "provider": "remote_chat_vlm",
    "model": "<the model name you were configured with>",
}


class RemoteChatVlmInspectionProvider(ProductionInspectionProvider):
    """Group B production provider: Jetson CV + remote chat-completions VLM."""

    provider_name = "remote_chat_vlm"
    production_eligible = True

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        max_image_bytes: int | None = None,
    ):
        self.base_url = (
            base_url if base_url is not None else os.getenv("VLM_BASE_URL", "")
        ).rstrip("/")
        self.model_name = model or os.getenv("VLM_MODEL") or ""
        self.api_key = api_key if api_key is not None else os.getenv("VLM_API_KEY", "")
        self.timeout = float(
            timeout if timeout is not None else os.getenv("VLM_TIMEOUT_SECONDS", "30")
        )
        self.max_image_bytes = int(
            max_image_bytes
            if max_image_bytes is not None
            else os.getenv("VLM_MAX_IMAGE_BYTES", str(5 * 1024 * 1024))
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.model_name)

    # ── Wire transport (isolated so tests can stub it without a live server) ──

    def _call_backend(self, payload: dict) -> object:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ── Image handling ──────────────────────────────────────────────────────

    def _resolve_image_data_url(self, ref: str) -> str:
        """Turn one ``image_references`` entry into an embeddable data URL.

        Only local file paths and already-encoded ``data:`` URLs are
        accepted. ``http(s)`` references are refused: the remote endpoint
        sits behind a restricted tunnel with no general-purpose outbound
        fetcher, and accepting arbitrary URLs here would be an SSRF surface
        with no corresponding benefit.
        """
        if ref.startswith("data:"):
            return ref
        if ref.startswith("http://") or ref.startswith("https://"):
            raise ProductionProviderError(
                "remote_chat_vlm_http_image_reference_not_supported: "
                "supply a local file path or a data: URL"
            )
        path = Path(ref)
        if not path.is_file():
            raise ProductionProviderError(f"remote_chat_vlm_image_not_found: {ref}")
        size = path.stat().st_size
        if size > self.max_image_bytes:
            raise ProductionProviderError(
                f"remote_chat_vlm_image_too_large: {size} bytes exceeds "
                f"max_image_bytes={self.max_image_bytes}"
            )
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    # ── Request construction ────────────────────────────────────────────────

    def _build_prompt(self, request: DetectionInspectionRequest) -> str:
        return (
            "You are a QC inspection assistant. Evaluate ONLY the supplied "
            "detection point against the image. Do not guess hidden facts, "
            "exact dimensions, or tolerances not stated in confirmed_content. "
            "If the checkpoint cannot be judged from this image, set "
            "disposition to 'review_required' and explain why in 'uncertainty'. "
            "Return exactly one JSON object matching this schema, no markdown, "
            "no extra text: "
            + json.dumps(_RESPONSE_SCHEMA_EXAMPLE, ensure_ascii=False, separators=(",", ":"))
            + "\ndetection_point_code: "
            + json.dumps(request.detection_point_code)
            + "\ncheckpoint_category: "
            + json.dumps(request.checkpoint_category)
            + "\nconfirmed_content: "
            + json.dumps(request.confirmed_content, ensure_ascii=False, separators=(",", ":"))
            + "\nprompt_schema_version: "
            + PROMPT_SCHEMA_VERSION
        )

    def _build_payload(self, request: DetectionInspectionRequest, data_url: str) -> dict:
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._build_prompt(request)},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 1024,
        }

    # ── Response parsing ────────────────────────────────────────────────────

    def _extract_content(self, raw: object) -> str:
        try:
            content = raw["choices"][0]["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProductionProviderSchemaError(
                f"remote_chat_vlm response missing choices[0].message.content: {exc}"
            ) from exc
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise ProductionProviderSchemaError("remote_chat_vlm response content is empty")
        return content

    def _parse_json_object(self, text: str) -> dict:
        cleaned = _JSON_FENCE_START.sub("", text.strip())
        cleaned = _JSON_FENCE_END.sub("", cleaned)
        start = cleaned.find("{")
        if start < 0:
            raise ProductionProviderSchemaError("remote_chat_vlm response is not JSON")
        try:
            value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError as exc:
            raise ProductionProviderSchemaError(
                f"remote_chat_vlm response invalid JSON: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ProductionProviderSchemaError("remote_chat_vlm response is not a JSON object")
        return value

    # ── Public interface ────────────────────────────────────────────────────

    def inspect(self, request: DetectionInspectionRequest) -> DetectionInspectionResult:
        if not self.is_configured:
            raise ProductionProviderNotConfigured("remote_chat_vlm_provider_not_configured")
        if not request.image_references:
            raise ProductionProviderError("remote_chat_vlm_no_image_reference")

        data_url = self._resolve_image_data_url(request.image_references[0])
        payload = self._build_payload(request, data_url)

        from src.qc_model import observability

        started = time.monotonic()
        try:
            raw = self._call_backend(payload)
        except (ProductionProviderNotConfigured, ProductionProviderError):
            raise
        except Exception as exc:  # transport / HTTP / decode → fail closed
            raise ProductionProviderError(
                f"remote_chat_vlm backend error: {type(exc).__name__}"
            ) from exc
        finally:
            observability.observe_latency(
                "remote_chat_vlm_inspect", (time.monotonic() - started) * 1000.0
            )

        content = self._extract_content(raw)
        parsed = self._parse_json_object(content)
        try:
            return parse_provider_response(parsed)
        except ValueError as exc:
            raise ProductionProviderSchemaError(f"remote_chat_vlm malformed output: {exc}") from exc
