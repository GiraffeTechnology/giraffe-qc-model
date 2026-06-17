"""Qwen / DashScope vision provider — real HTTP calls, no SDK dependency."""
from __future__ import annotations
import base64
import json
import os
import re
import time
from pathlib import Path

import httpx

from src.llm.base import LLMProvider, ImageCompareResult

_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")
_VISION_ENDPOINT = f"{_BASE_URL}/services/aigc/multimodal-generation/generation"
_VISION_MODEL = os.getenv("QWEN_VISION_MODEL", "qwen-vl-plus")
_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))


def _encode_image(path: str) -> str:
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def _extract_json(text: str) -> dict:
    # Strip markdown fences (``` or ```json ... ```)
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip(" \n`")
    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Find the first {...} block
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"raw_text": text}


_JSON_SCHEMA_HINT = (
    '严格只输出以下JSON，不加任何解释或markdown：\n'
    '{"overall_result":"pass|needs_fix|reject","similarity_score":0.0,'
    '"severity":"low|medium|high","feedback_zh":"中文反馈",'
    '"feedback_en":"English feedback",'
    '"deviations":[{"field":"","expected":"","actual":"","severity":""}]}'
)


class QwenProvider(LLMProvider):
    """Real Qwen vision API implementation."""

    @property
    def provider_name(self) -> str:
        return "qwen"

    @property
    def model_name(self) -> str:
        return _VISION_MODEL

    def _api_key(self) -> str:
        return os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY") or ""

    def compare_images(
        self,
        standard_paths: list[str],
        production_paths: list[str],
        requirements: str = "",
        notes: str = "",
    ) -> ImageCompareResult:
        all_paths = standard_paths + production_paths
        content: list[dict] = []

        # Prepend schema hint so it appears before images (helps compliance)
        content.append({"text": f"你是质检AI。{_JSON_SCHEMA_HINT}"})

        for i, p in enumerate(all_paths):
            label = "标准样本" if i < len(standard_paths) else "生产图"
            content.append({"text": f"[{label} {i + 1}]"})
            content.append({"image": _encode_image(p)})

        user_text = "对比以上标准样本和生产图，输出JSON。"
        if requirements:
            user_text += f"订单要求：{requirements}。"
        if notes:
            user_text += f"工艺备注：{notes}。"
        content.append({"text": user_text})

        payload = {
            "model": _VISION_MODEL,
            "input": {
                "messages": [
                    {"role": "user", "content": content},
                ]
            },
        }

        api_key = self._api_key()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        http_status = 0
        elapsed_ms = 0
        raw_text = ""

        for attempt in range(_MAX_RETRIES + 1):
            t0 = time.time()
            try:
                resp = httpx.post(
                    _VISION_ENDPOINT,
                    headers=headers,
                    json=payload,
                    timeout=_TIMEOUT,
                )
                elapsed_ms = int((time.time() - t0) * 1000)
                http_status = resp.status_code
                resp.raise_for_status()
                body = resp.json()
                raw_text = (
                    body.get("output", {})
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if isinstance(raw_text, list):
                    raw_text = " ".join(
                        c.get("text", "") for c in raw_text if isinstance(c, dict)
                    )
                break
            except Exception as exc:
                last_exc = exc
                http_status = getattr(getattr(exc, "response", None), "status_code", 0) or http_status
                elapsed_ms = int((time.time() - t0) * 1000)
                if attempt < _MAX_RETRIES:
                    time.sleep(2 ** attempt)
        else:
            raise RuntimeError(
                f"Qwen API failed after {_MAX_RETRIES + 1} attempts "
                f"(HTTP {http_status}): {last_exc}"
            )

        parsed = _extract_json(raw_text)
        return ImageCompareResult(
            overall_result=parsed.get("overall_result", "unknown"),
            similarity_score=float(parsed.get("similarity_score", 0.0)),
            severity=parsed.get("severity", "unknown"),
            feedback_zh=parsed.get("feedback_zh", ""),
            feedback_en=parsed.get("feedback_en", ""),
            deviations=parsed.get("deviations", []),
            provider=self.provider_name,
            model=_VISION_MODEL,
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            raw_summary=raw_text[:500],
        )
