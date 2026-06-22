"""Qwen DashScope multimodal provider adapter.

Converts MultimodalRequest into DashScope-compatible HTTP payload.
Contains NO QC business logic — only transport/encoding.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path

import httpx

from src.multimodal.config import (
    multimodal_enable_real_calls,
    multimodal_max_retries,
    multimodal_timeout_seconds,
)
from src.multimodal.errors import MultimodalConfigError, MultimodalProviderError
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import MultimodalMessagePart, MultimodalRequest, MultimodalRawResponse

logger = logging.getLogger(__name__)

_DASHSCOPE_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
_DEFAULT_MODEL = "qwen-vl-max"


def _resolve_model() -> str:
    return (
        os.getenv("QWEN_MULTIMODAL_MODEL")
        or os.getenv("MULTIMODAL_DEFAULT_MODEL")
        or _DEFAULT_MODEL
    )


def _encode_image(path: str) -> str:
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def _build_content(parts: list[MultimodalMessagePart]) -> list[dict]:
    content: list[dict] = []
    for part in parts:
        if part.type == "text" and part.text:
            content.append({"text": part.text})
        elif part.type == "image":
            if part.image_base64:
                content.append({"image": part.image_base64})
            elif part.image_path:
                content.append({"image": _encode_image(part.image_path)})
        elif part.type == "json" and part.json_data is not None:
            content.append({"text": json.dumps(part.json_data, ensure_ascii=False)})
    return content


class QwenDashScopeProvider(MultimodalProvider):
    """DashScope Qwen-VL multimodal provider.

    Only converts MultimodalRequest to DashScope payload and returns raw response.
    All QC business logic belongs in capability modules, not here.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY") or ""
        self._model = model or _resolve_model()
        self._timeout = multimodal_timeout_seconds()
        self._max_retries = multimodal_max_retries()

    @property
    def provider_name(self) -> str:
        return "qwen"

    @property
    def model_name(self) -> str:
        return self._model

    def _check_config(self) -> None:
        if not multimodal_enable_real_calls():
            raise MultimodalConfigError(
                "Real multimodal calls are disabled. Set MULTIMODAL_ENABLE_REAL_CALLS=true."
            )
        if not self._api_key:
            raise MultimodalConfigError(
                "Qwen API key missing. Set QWEN_API_KEY or DASHSCOPE_API_KEY."
            )

    def generate(self, request: MultimodalRequest) -> MultimodalRawResponse:
        self._check_config()

        content = _build_content(request.messages)
        payload = {
            "model": self._model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {"result_format": "message"},
        }

        # Mask key in logs
        masked = (self._api_key[:8] + "****") if len(self._api_key) > 8 else "****"
        logger.debug("QwenDashScopeProvider.generate capability=%s model=%s key=%s", request.capability, self._model, masked)

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        http_status = 0
        elapsed_ms = 0

        for attempt in range(self._max_retries + 1):
            t0 = time.time()
            try:
                resp = httpx.post(_DASHSCOPE_ENDPOINT, json=payload, headers=headers, timeout=self._timeout)
                elapsed_ms = int((time.time() - t0) * 1000)
                http_status = resp.status_code
                resp.raise_for_status()
                body = resp.json()
                raw_text = (
                    body.get("output", {})
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", [{}])[0]
                    .get("text", "")
                )
                if isinstance(raw_text, list):
                    raw_text = " ".join(c.get("text", "") for c in raw_text if isinstance(c, dict))
                token_usage = body.get("usage")
                return MultimodalRawResponse(
                    provider=self.provider_name,
                    model=self._model,
                    raw_text=raw_text,
                    latency_ms=elapsed_ms,
                    http_status=http_status,
                    token_usage=token_usage,
                )
            except Exception as exc:
                last_exc = exc
                elapsed_ms = int((time.time() - t0) * 1000)
                http_status = getattr(getattr(exc, "response", None), "status_code", 0) or http_status
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)

        raise MultimodalProviderError(
            f"QwenDashScope failed after {self._max_retries + 1} attempts (HTTP {http_status}): {last_exc}"
        )
