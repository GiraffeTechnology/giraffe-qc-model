"""MultimodalQCService — provider-neutral entry point for QC inspection."""
from __future__ import annotations

import logging
from typing import Any

from src.multimodal.providers.registry import get_provider
from src.multimodal.router import CapabilityRouter, RouterResult, RoutingContext

logger = logging.getLogger(__name__)


class MultimodalQCService:
    """Provider-neutral QC service. Delegates to CapabilityRouter.

    Provider selection is driven by:
      MULTIMODAL_PROVIDER=qwen|openai|anthropic|local_mnn|mock
      MULTIMODAL_ENABLE_REAL_CALLS=true|false (default false → MockProvider)
    """

    def __init__(self, provider_name: str | None = None) -> None:
        self._provider_name = provider_name
        self._router: CapabilityRouter | None = None

    def _get_router(self) -> CapabilityRouter:
        if self._router is None:
            provider = get_provider(self._provider_name)
            self._router = CapabilityRouter(provider=provider)
        return self._router

    def run_inspection(
        self,
        standard_image_paths: list[str],
        captured_image_path: str,
        qc_points: list[dict[str, Any]],
        tenant_id: str,
        sku_id: str,
        standard_id: str,
        inspection_id: str,
        simulated_local_result: str | None = None,
    ) -> RouterResult:
        context = RoutingContext(
            tenant_id=tenant_id,
            sku_id=sku_id,
            standard_id=standard_id,
            inspection_id=inspection_id,
        )
        router = self._get_router()
        return router.run(
            standard_image_paths=standard_image_paths,
            captured_image_path=captured_image_path,
            qc_points=qc_points,
            context=context,
            simulated_local_result=simulated_local_result,
        )
