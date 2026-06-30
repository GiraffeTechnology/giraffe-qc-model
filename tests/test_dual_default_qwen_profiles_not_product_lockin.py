"""Dual default profiles exist, but the product is not Qwen-locked (PRD §3, §24.3)."""
from __future__ import annotations

from src.qc_model.providers.base import VisionLanguageModelProvider
from src.qc_model.providers.compat_provider import MainstreamVLMAdapter
from src.qc_model.runtime_profiles import (
    DEFAULT_RUNTIME_PROFILES,
    MAINSTREAM_LLM_VLM_ADAPTERS_SUPPORTED,
    RuntimeEnvironment,
    default_runtime_profiles_config,
    get_runtime_profile,
)


def test_two_default_profiles_configured():
    assert set(DEFAULT_RUNTIME_PROFILES.keys()) == {
        RuntimeEnvironment.DESKTOP_PC_MNN,
        RuntimeEnvironment.SERVER,
    }


def test_desktop_and_server_models():
    cfg = default_runtime_profiles_config()["default_runtime_profiles"]
    assert cfg["desktop_pc_mnn"]["model"] == "qwen3.5-vl-2b-mnn"
    assert cfg["server"]["model"] == "qwen3.5-vl-8b-int4"
    assert cfg["desktop_pc_mnn"]["provider"] == "qwen3_5_vl"
    assert cfg["server"]["provider"] == "qwen3_5_vl"


def test_config_advertises_provider_compatibility():
    cfg = default_runtime_profiles_config()
    assert cfg["provider_compatibility"]["mainstream_llm_vlm_adapters_supported"] is True
    assert MAINSTREAM_LLM_VLM_ADAPTERS_SUPPORTED is True


def test_profiles_select_by_environment():
    assert get_runtime_profile("desktop_pc_mnn").role == "default_desktop_pc_mnn_visual_reasoning_profile"
    assert get_runtime_profile("server").role == "default_server_visual_reasoning_profile"


def test_provider_can_be_replaced_through_adapter():
    """A non-Qwen provider satisfies the same abstraction — no vendor lock-in."""
    adapter = MainstreamVLMAdapter(lambda req: [], provider_name="vendor_x", model_name="vendor-x-vlm")
    assert isinstance(adapter, VisionLanguageModelProvider)
    # The product never asserts the provider is Qwen.
    assert adapter.provider_name != "qwen3_5_vl"


def test_default_profile_models_are_not_generic_single_model():
    """Must recognize TWO default profiles, not one generic 'qwen3.5-vl'."""
    models = {p.model for p in DEFAULT_RUNTIME_PROFILES.values()}
    assert models == {"qwen3.5-vl-2b-mnn", "qwen3.5-vl-8b-int4"}
    assert "qwen3.5-vl" not in models  # not the generic single name
