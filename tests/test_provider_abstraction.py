"""Provider abstraction tests (PRD §23.2)."""
from __future__ import annotations

import ast
from pathlib import Path

from src.qc_model.providers.base import (
    VisionLanguageModelProvider,
    VisualInspectionRequest,
    VisualInspectionResponse,
)
from src.qc_model.providers.compat_provider import MainstreamVLMAdapter
from src.qc_model.providers.mock_provider import MockVLMProvider
from src.qc_model.providers.registry import (
    get_provider,
    get_provider_for_profile,
    register_provider,
)
from src.qc_model.runtime_profiles import (
    RuntimeEnvironment,
    get_runtime_profile,
)


def _blank_request() -> VisualInspectionRequest:
    return VisualInspectionRequest(
        sku_id="sku1",
        station_id="st1",
        capture_protocol={},
        reference_image_paths=["ref.png"],
        inspection_image_paths=["cap.png"],
        detection_points=[{"code": "missing_rhinestone", "checkpoint_category": "visual_defect"}],
    )


def test_tablet_mnn_default_profile_is_2b_mnn():
    profile = get_runtime_profile("tablet_mnn")
    assert profile.model == "qwen3.5-vl-2b-mnn"
    assert profile.environment == RuntimeEnvironment.TABLET_MNN


def test_server_default_profile_is_8b_int4():
    profile = get_runtime_profile("server")
    assert profile.model == "qwen3.5-vl-8b-int4"
    assert profile.environment == RuntimeEnvironment.SERVER


def test_runtime_profile_selection_by_environment(monkeypatch):
    monkeypatch.setenv("QC_VISION_RUNTIME_ENV", "tablet_mnn")
    assert get_runtime_profile().model == "qwen3.5-vl-2b-mnn"
    monkeypatch.setenv("QC_VISION_RUNTIME_ENV", "server")
    assert get_runtime_profile().model == "qwen3.5-vl-8b-int4"


def test_unknown_environment_falls_back_to_server():
    assert get_runtime_profile("nonsense").model == "qwen3.5-vl-8b-int4"


def test_product_services_do_not_import_qwen_specific_classes():
    """Product logic modules must not import the concrete Qwen class.

    Only the registry (the seam) is allowed to know the vendor class, and even
    it imports it lazily inside a function.
    """
    product_modules = [
        "src/qc_model/runner.py",
        "src/qc_model/finalizer.py",
        "src/qc_model/lifecycle.py",
        "src/qc_model/capture_quality.py",
        "src/qc_model/feedback_escalation.py",
    ]
    for rel in product_modules:
        source = Path(rel).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                names.extend(alias.name for alias in node.names)
                for name in names:
                    assert "qwen3_5_vl" not in name and "Qwen35VL" not in name, (
                        f"{rel} imports Qwen-specific symbol {name!r}; product "
                        "logic must depend on the provider abstraction only."
                    )


def test_mocked_provider_satisfies_interface():
    provider = MockVLMProvider()
    assert isinstance(provider, VisionLanguageModelProvider)
    response = provider.inspect(_blank_request())
    assert isinstance(response, VisualInspectionResponse)
    assert response.valid is True


def test_mainstream_adapter_satisfies_same_interface():
    def fake_call(request):
        return [{"code": "missing_rhinestone", "result": "pass", "evidence": "ok"}]

    adapter = MainstreamVLMAdapter(fake_call, provider_name="openai_vlm", model_name="gpt-vision")
    assert isinstance(adapter, VisionLanguageModelProvider)
    response = adapter.inspect(_blank_request())
    assert response.valid is True
    assert response.provider == "openai_vlm"
    assert response.checkpoint_results[0].result == "pass"


def test_default_provider_for_server_profile_is_qwen_but_fails_closed():
    provider = get_provider_for_profile(get_runtime_profile("server"))
    assert provider.provider_name == "qwen3_5_vl"
    assert provider.model_name == "qwen3.5-vl-8b-int4"
    # Phase 1: no real backend → fail closed (review_required), never pass.
    response = provider.inspect(_blank_request())
    assert response.valid is False
    assert response.overall_result == "review_required"


def test_provider_failure_returns_review_required_not_pass():
    def boom(request):
        raise RuntimeError("backend down")

    adapter = MainstreamVLMAdapter(boom)
    response = adapter.inspect(_blank_request())
    assert response.valid is False
    assert response.overall_result == "review_required"


def test_mainstream_adapter_can_be_registered_and_resolved():
    register_provider(
        "registered_mainstream",
        lambda profile: MainstreamVLMAdapter(
            lambda req: [], provider_name="registered_mainstream", model_name=profile.model
        ),
    )
    from src.qc_model.runtime_profiles import RuntimeProfile

    profile = RuntimeProfile(
        environment=RuntimeEnvironment.SERVER,
        provider="registered_mainstream",
        model="some-model",
        role="r",
    )
    provider = get_provider_for_profile(profile)
    assert provider.provider_name == "registered_mainstream"
