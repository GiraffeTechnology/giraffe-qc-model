"""Local MNN on-device provider stub.

Represents the interface for Android/edge local model inference.
Does NOT fake real inference — returns review_required if MNN is not provisioned.
"""
from __future__ import annotations

import json

from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import MultimodalRequest, MultimodalRawResponse


class LocalMnnProviderAdapter(MultimodalProvider):
    """Local MNN on-device provider. Returns review_required if not provisioned."""

    @property
    def provider_name(self) -> str:
        return "local_mnn"

    @property
    def model_name(self) -> str:
        import os
        return os.getenv("LOCAL_MNN_MODEL", "qwen3-vl-2b-instruct-mnn")

    def generate(self, request: MultimodalRequest) -> MultimodalRawResponse:
        # MNN JNI inference is not wired in this stub; return on_device_model_not_provisioned
        stub_json = {
            "overall_result": "review_required",
            "reason": "on_device_model_not_provisioned",
            "engine": "local_mnn",
        }
        return MultimodalRawResponse(
            provider=self.provider_name,
            model=self.model_name,
            raw_text=json.dumps(stub_json),
            raw_json=stub_json,
            http_status=None,
            latency_ms=0,
            metadata={"stub": True, "provisioned": False},
        )
