"""Tests for runtime edition configuration."""
from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

from src.runtime.editions import Edition, EditionConfig, get_edition_config


@contextmanager
def patch_env(overrides: dict):
    """Temporarily replace all QC_* env vars with the given overrides."""
    qc_keys = [k for k in os.environ if k.startswith("QC_")]
    saved = {k: os.environ.pop(k) for k in qc_keys}
    for k, v in overrides.items():
        os.environ[k] = v
    try:
        yield
    finally:
        for k in overrides:
            os.environ.pop(k, None)
        for k, v in saved.items():
            os.environ[k] = v


class TestEditionDefaults:
    def test_pad_local_defaults(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal"}):
            cfg = get_edition_config()
        assert cfg.edition == Edition.PAD_LOCAL
        assert cfg.model_name == "Qwen3-VL-2B-Instruct-MNN"
        assert cfg.allow_qwen_api is False
        assert cfg.allow_cloud_inference is False

    def test_server_defaults(self):
        with patch_env({"QC_RUNTIME_EDITION": "server"}):
            cfg = get_edition_config()
        assert cfg.edition == Edition.SERVER
        assert cfg.model_name == "Qwen3-VL-8B"
        assert cfg.allow_qwen_api is True
        assert cfg.allow_cloud_inference is True

    def test_default_edition_is_pad_local(self):
        with patch_env({}):
            cfg = get_edition_config()
        assert cfg.edition == Edition.PAD_LOCAL

    def test_unknown_edition_falls_back_to_pad_local(self):
        with patch_env({"QC_RUNTIME_EDITION": "unknown_xyz"}):
            cfg = get_edition_config()
        assert cfg.edition == Edition.PAD_LOCAL


class TestEditionOverrides:
    def test_model_name_override(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal", "QC_MODEL_NAME": "custom-model"}):
            cfg = get_edition_config()
        assert cfg.model_name == "custom-model"

    def test_allow_qwen_api_true_override_on_pad(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal", "QC_ALLOW_QWEN_API": "true"}):
            cfg = get_edition_config()
        assert cfg.allow_qwen_api is True

    def test_allow_qwen_api_false_stays_false(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal", "QC_ALLOW_QWEN_API": "false"}):
            cfg = get_edition_config()
        assert cfg.allow_qwen_api is False

    def test_disable_cloud_inference_on_server(self):
        with patch_env({"QC_RUNTIME_EDITION": "server", "QC_ALLOW_CLOUD_INFERENCE": "false"}):
            cfg = get_edition_config()
        assert cfg.allow_cloud_inference is False

    def test_allow_qwen_api_truthy_values(self):
        for truthy in ("1", "yes", "true", "True", "YES"):
            with patch_env({"QC_ALLOW_QWEN_API": truthy}):
                cfg = get_edition_config()
            assert cfg.allow_qwen_api is True, f"expected True for '{truthy}'"


class TestPadEditionInferenceRestrictions:
    def test_pad_disables_qwen_api_by_default(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal"}):
            cfg = get_edition_config()
        assert cfg.allow_qwen_api is False

    def test_pad_disables_cloud_inference_by_default(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal"}):
            cfg = get_edition_config()
        assert cfg.allow_cloud_inference is False

    def test_pad_uses_small_model(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal"}):
            cfg = get_edition_config()
        assert "2B" in cfg.model_name


class TestServerEditionInferencePermissions:
    def test_server_allows_qwen_api_by_default(self):
        with patch_env({"QC_RUNTIME_EDITION": "server"}):
            cfg = get_edition_config()
        assert cfg.allow_qwen_api is True

    def test_server_allows_cloud_inference_by_default(self):
        with patch_env({"QC_RUNTIME_EDITION": "server"}):
            cfg = get_edition_config()
        assert cfg.allow_cloud_inference is True

    def test_server_uses_larger_model(self):
        with patch_env({"QC_RUNTIME_EDITION": "server"}):
            cfg = get_edition_config()
        assert "8B" in cfg.model_name


class TestSampleDbSharedByEditions:
    """Confirm sample DB and admin page do not branch by edition."""

    def test_edition_config_has_no_sample_db_flag(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal"}):
            cfg = get_edition_config()
        # Sample DB access is unconditional — not gated by edition config
        assert not hasattr(cfg, "sample_db_enabled")
        assert not hasattr(cfg, "admin_enabled")

    def test_inference_fields_differ_between_editions(self):
        with patch_env({"QC_RUNTIME_EDITION": "padLocal"}):
            pad = get_edition_config()
        with patch_env({"QC_RUNTIME_EDITION": "server"}):
            server = get_edition_config()
        # Only inference fields differ between editions
        assert pad.model_name != server.model_name
        assert pad.allow_qwen_api != server.allow_qwen_api
        assert pad.allow_cloud_inference != server.allow_cloud_inference
