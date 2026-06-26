"""DashScope Qwen3-VL via OpenAI-compatible endpoint (B1 cloud oracle path).

Requires: pip install openai>=1.0
API key: DASHSCOPE_API_KEY or QWEN_TEST_API_KEY env var.
Mark tests using this provider with @pytest.mark.real_api.
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

from src.llm.base import LLMProvider, ImageCompareResult
from src.llm.result_parser import QcResultParser

_CLOUD_BASE_URL = os.getenv(
    "QWEN_CLOUD_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
_ORACLE_MODEL = os.getenv("QWEN_ORACLE_MODEL", "qwen3-vl-8b-instruct")
_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

_JSON_SCHEMA_HINT = (
    "严格只输出以下JSON，不加任何解释或markdown：\n"
    '{"overall_result":"pass|needs_fix|reject","similarity_score":0.0,'
    '"severity":"low|medium|high","feedback_zh":"中文反馈",'
    '"feedback_en":"English feedback",'
    '"deviations":[{"field":"","expected":"","actual":"","severity":""}]}'
)


def _b64_image(path: str) -> str:
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


class DashScopeOpenAIProvider(LLMProvider):
    """Qwen3-VL via DashScope OpenAI-compatible API (cloud oracle)."""

    def __init__(self, model: str | None = None, base_url: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package required for DashScopeOpenAIProvider. "
                "Install with: pip install openai>=1.0"
            ) from exc

        self._model = model or _ORACLE_MODEL
        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_TEST_API_KEY")
        if not api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY or QWEN_TEST_API_KEY environment variable required"
            )
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or _CLOUD_BASE_URL,
        )

    @property
    def provider_name(self) -> str:
        return "dashscope_openai"

    @property
    def model_name(self) -> str:
        return self._model

    def compare_images(
        self,
        standard_paths: list[str],
        production_paths: list[str],
        requirements: str = "",
        notes: str = "",
    ) -> ImageCompareResult:
        content: list[dict] = [
            {"type": "text", "text": f"你是质检AI。{_JSON_SCHEMA_HINT}"}
        ]

        for i, p in enumerate(standard_paths):
            content.append({"type": "text", "text": f"[标准样本 {i + 1}]"})
            content.append({"type": "image_url", "image_url": {"url": _b64_image(p)}})

        for i, p in enumerate(production_paths):
            content.append({"type": "text", "text": f"[生产图 {i + 1}]"})
            content.append({"type": "image_url", "image_url": {"url": _b64_image(p)}})

        user_text = "对比以上标准样本和生产图，输出JSON。"
        if requirements:
            user_text += f"订单要求：{requirements}。"
        if notes:
            user_text += f"工艺备注：{notes}。"
        content.append({"type": "text", "text": user_text})

        t0 = time.time()
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        raw = resp.choices[0].message.content or ""
        parsed = QcResultParser.parse(raw)

        return ImageCompareResult(
            overall_result=parsed.get("overall_result", "unknown"),
            similarity_score=float(parsed.get("similarity_score", 0.0)),
            severity=parsed.get("severity", "unknown"),
            feedback_zh=parsed.get("feedback_zh", ""),
            feedback_en=parsed.get("feedback_en", ""),
            deviations=parsed.get("deviations", []),
            provider=self.provider_name,
            model=self._model,
            http_status=200,
            elapsed_ms=elapsed_ms,
            raw_summary=raw[:500],
        )

    def list_available_models(self) -> list[str]:
        """Probe DashScope for available model names (used in B1 test)."""
        try:
            models = self._client.models.list()
            return [m.id for m in models.data]
        except Exception:
            return []
