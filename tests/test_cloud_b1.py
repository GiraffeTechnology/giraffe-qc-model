"""B1 Cloud tests — DashScope Qwen3-VL via OpenAI-compatible endpoint.

Real API calls; excluded from CI by default.
Run with:
  DASHSCOPE_API_KEY=sk-xxx pytest -m real_api tests/test_cloud_b1.py -v

Red lines enforced here:
  - Key only via env var; never printed, logged, or asserted
  - MAX_REAL_CALLS (default 20) caps total calls per session
  - <think> stripping verified even for non-thinking models
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_api

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots" / "cloud"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

_call_counter: dict[str, int] = {"n": 0}


@pytest.fixture(scope="session", autouse=True)
def require_api_key():
    key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_TEST_API_KEY")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY / QWEN_TEST_API_KEY not set — skipping all B1 tests")


@pytest.fixture(scope="session")
def max_calls() -> int:
    return int(os.getenv("MAX_REAL_CALLS", "20"))


@pytest.fixture(autouse=True)
def cost_gate(max_calls: int):
    if _call_counter["n"] >= max_calls:
        pytest.skip(f"MAX_REAL_CALLS={max_calls} reached — skipping remaining B1 tests")
    _call_counter["n"] += 1


@pytest.fixture(scope="session")
def provider():
    from src.llm.dashscope_openai_provider import DashScopeOpenAIProvider
    return DashScopeOpenAIProvider()


@pytest.fixture(scope="session")
def good_image() -> str:
    for candidate in [
        FIXTURES_DIR / "good" / "product_ok.png",
        FIXTURES_DIR / "red_square.png",
    ]:
        if candidate.exists():
            return str(candidate)
    pytest.skip("No good-image fixture found; run: python scripts/generate_test_fixtures.py")


@pytest.fixture(scope="session")
def scratch_image() -> str:
    for candidate in [
        FIXTURES_DIR / "defect_scratch" / "scratch_01.png",
        FIXTURES_DIR / "red_square_with_dot.png",
    ]:
        if candidate.exists():
            return str(candidate)
    pytest.skip("No defect fixture found")


def _save_snapshot(name: str, raw: str, data: dict) -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "fixture": name,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": data,
    }
    (SNAPSHOTS_DIR / f"{name}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class TestCloudProbe:
    def test_probe_available_models(self, provider):
        """List available models; write to snapshot for audit trail."""
        models = provider.list_available_models()
        _save_snapshot("probe_models", "", {"models": models})
        assert isinstance(models, list)


class TestCloudParsing:
    def test_schema_conformance_all_fields(self, provider, good_image):
        result = provider.compare_images([good_image], [good_image])
        _save_snapshot("schema_check", result.raw_summary, {
            "overall_result": result.overall_result,
            "similarity_score": result.similarity_score,
            "severity": result.severity,
            "elapsed_ms": result.elapsed_ms,
            "provider": result.provider,
            "model": result.model,
            "deviations_count": len(result.deviations),
        })
        assert result.overall_result in ("pass", "needs_fix", "reject", "unknown")
        assert 0.0 <= result.similarity_score <= 1.0
        assert result.severity in ("low", "medium", "high", "unknown")
        assert isinstance(result.deviations, list)
        assert result.provider == "dashscope_openai"
        assert result.elapsed_ms >= 0

    def test_think_stripping_defensive(self):
        """Parser strips <think> even when injected; exercises the defence layer."""
        from src.llm.result_parser import QcResultParser
        injected = (
            "<think>ignore this</think>"
            '{"overall_result":"pass","severity":"low","similarity_score":0.95,"deviations":[]}'
        )
        parsed = QcResultParser.parse(injected)
        assert parsed["overall_result"] == "pass"
        dumped = json.dumps(parsed)
        assert "<think>" not in dumped

    def test_good_vs_good_tends_toward_pass(self, provider, good_image):
        result = provider.compare_images([good_image], [good_image])
        _save_snapshot("good_self_compare", result.raw_summary, {
            "overall_result": result.overall_result,
            "similarity_score": result.similarity_score,
        })
        assert result.overall_result in ("pass", "needs_fix"), (
            f"Identical image vs itself returned {result.overall_result!r}"
        )

    def test_defect_direction_schema_valid(self, provider, good_image, scratch_image):
        """Defect image vs good standard: must not crash and must be schema-valid."""
        result = provider.compare_images([good_image], [scratch_image])
        _save_snapshot("defect_vs_good", result.raw_summary, {
            "overall_result": result.overall_result,
            "severity": result.severity,
            "deviations_count": len(result.deviations),
        })
        assert result.overall_result in ("pass", "needs_fix", "reject", "unknown")
        assert isinstance(result.deviations, list)

    def test_response_latency_recorded(self, provider, good_image):
        result = provider.compare_images([good_image], [good_image])
        _save_snapshot("latency_check", result.raw_summary, {"elapsed_ms": result.elapsed_ms})
        assert result.elapsed_ms > 0
