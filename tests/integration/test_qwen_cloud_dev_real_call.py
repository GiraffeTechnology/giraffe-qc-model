"""Opt-in integration test for real DashScope QWEN cloud API calls.

Run only when all of the following env vars are set:
  RUN_QWEN_INTEGRATION=1
  QC_ENGINE_MODE=cloud_qwen_dev
  LLM_ENABLE_REAL_CALLS=true
  DASHSCOPE_API_KEY=<key>   (or QWEN_API_KEY=<key>)

Example:
  RUN_QWEN_INTEGRATION=1 \\
  QC_ENGINE_MODE=cloud_qwen_dev \\
  LLM_ENABLE_REAL_CALLS=true \\
  DASHSCOPE_API_KEY=$DASHSCOPE_API_KEY \\
  uv run pytest tests/integration/test_qwen_cloud_dev_real_call.py -v

Safety:
  - All tests are skipped unless RUN_QWEN_INTEGRATION=1 is set explicitly.
  - API key is never printed or asserted — only presence is checked.
  - No key is committed to the repository.
"""
from __future__ import annotations

import os
import pytest

from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    StandardPhotoInput,
)

FIXTURES = "tests/fixtures/qc"

# Skip entire module unless integration flag is set
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_QWEN_INTEGRATION") != "1",
    reason="Set RUN_QWEN_INTEGRATION=1 to run real DashScope API tests",
)


def _require_cloud_env(monkeypatch):
    """Ensure all required env vars for cloud_qwen_dev are present."""
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
    if not api_key:
        pytest.skip("DASHSCOPE_API_KEY / QWEN_API_KEY not set")
    if os.getenv("QC_ENGINE_MODE") != "cloud_qwen_dev":
        pytest.skip("QC_ENGINE_MODE must be cloud_qwen_dev")
    if os.getenv("LLM_ENABLE_REAL_CALLS") != "true":
        pytest.skip("LLM_ENABLE_REAL_CALLS must be true")
    monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
    monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")


@pytest.fixture
def qc_points():
    return [
        QcPointInput(qc_point_id="QC-01", qc_point_code="color",  name="Color",  description="Surface color must match standard"),
        QcPointInput(qc_point_id="QC-02", qc_point_code="defect", name="Defect", description="No surface defects allowed"),
    ]


@pytest.fixture
def std_photos():
    return [StandardPhotoInput(photo_id="STD-01", local_path=f"{FIXTURES}/standard_red_square.png", angle="front")]


@pytest.fixture
def ctx():
    return InspectionContext(
        tenant_id="tenant_integration_test",
        sku_id="SKU-RED-SQUARE",
        standard_id="STD-RED-SQUARE-01",
        inspection_id="INS-INTEGRATION-01",
    )


class TestRealDashScopeApiCall:
    def test_pass_case_returns_valid_schema(self, monkeypatch, std_photos, qc_points, ctx):
        """Pass case: capture identical to standard → expect pass or review_required."""
        _require_cloud_env(monkeypatch)

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        cap = CapturePhotoInput(photo_id="CAP-01", local_path=f"{FIXTURES}/capture_red_square_pass.png")
        ids = [p.qc_point_id for p in qc_points]

        result = provider.inspect(
            standard_photos=std_photos,
            captured_photo=cap,
            qc_points=qc_points,
            context=ctx,
        )

        assert result.overall_result in ("pass", "fail", "review_required")
        assert result.engine in ("cloud_qwen", "cloud_qwen_dev")
        assert result.engine != "local_qwen_mnn"
        assert 0.0 <= result.confidence <= 1.0
        assert len(result.items) == len(qc_points)
        for item in result.items:
            assert item.qc_point_id in ids
            assert item.result in ("pass", "fail", "review_required")
            assert 0.0 <= item.confidence <= 1.0

    def test_defect_case_not_pass(self, monkeypatch, std_photos, qc_points, ctx):
        """Defect case: capture has visible defect → must not return pass for defect point."""
        _require_cloud_env(monkeypatch)

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        cap = CapturePhotoInput(photo_id="CAP-02", local_path=f"{FIXTURES}/capture_red_square_defect.png")

        result = provider.inspect(
            standard_photos=std_photos,
            captured_photo=cap,
            qc_points=qc_points,
            context=ctx,
        )

        # A visible defect must not produce a confident "pass" overall
        # It's acceptable for model to return review_required if uncertain
        assert result.overall_result in ("fail", "review_required")

    def test_wrong_color_case_not_pass(self, monkeypatch, std_photos, qc_points, ctx):
        """Wrong color: blue capture vs red standard → must not be pass."""
        _require_cloud_env(monkeypatch)

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        cap = CapturePhotoInput(photo_id="CAP-03", local_path=f"{FIXTURES}/capture_wrong_color.png")

        result = provider.inspect(
            standard_photos=std_photos,
            captured_photo=cap,
            qc_points=qc_points,
            context=ctx,
        )

        assert result.overall_result in ("fail", "review_required")

    def test_engine_is_never_local_qwen_mnn(self, monkeypatch, std_photos, qc_points, ctx):
        """Cloud call must never report engine=local_qwen_mnn."""
        _require_cloud_env(monkeypatch)

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        cap = CapturePhotoInput(photo_id="CAP-04", local_path=f"{FIXTURES}/capture_red_square_pass.png")

        result = provider.inspect(
            standard_photos=std_photos,
            captured_photo=cap,
            qc_points=qc_points,
            context=ctx,
        )

        assert result.engine != "local_qwen_mnn"

    def test_api_key_not_in_result(self, monkeypatch, std_photos, qc_points, ctx):
        """The API key must not appear anywhere in the parsed result."""
        _require_cloud_env(monkeypatch)
        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY", "")

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        cap = CapturePhotoInput(photo_id="CAP-05", local_path=f"{FIXTURES}/capture_red_square_pass.png")

        result = provider.inspect(
            standard_photos=std_photos,
            captured_photo=cap,
            qc_points=qc_points,
            context=ctx,
        )

        result_str = result.model_dump_json()
        if len(api_key) > 8:
            assert api_key not in result_str

    def test_hallucinated_ids_rejected(self, monkeypatch, std_photos, ctx):
        """Parser must reject any QC point IDs the model hallucinates."""
        _require_cloud_env(monkeypatch)

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        cap = CapturePhotoInput(photo_id="CAP-06", local_path=f"{FIXTURES}/capture_red_square_pass.png")
        points = [QcPointInput(qc_point_id="QC-SPECIFIC-01", qc_point_code="specific", name="Specific", description="Specific point")]

        result = provider.inspect(
            standard_photos=std_photos,
            captured_photo=cap,
            qc_points=points,
            context=ctx,
        )

        valid_ids = {"QC-SPECIFIC-01"}
        for item in result.items:
            assert item.qc_point_id in valid_ids, (
                f"Hallucinated ID {item.qc_point_id!r} was not rejected"
            )
