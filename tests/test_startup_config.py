"""Tests for SESSION_SECRET enforcement (A2), seed gating (A2), and password
comparison hardening (A4)."""
from __future__ import annotations

import pytest

from src.api.auth import DEV_SESSION_SECRET_DEFAULT
from src.api.startup import validate_startup_config
from src.pad.session_service import (
    _make_password_hash,
    _verify_password,
    seed_demo_operators_allowed,
)


class TestSessionSecretEnforcement:
    def test_unset_secret_outside_test_fails(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            validate_startup_config()

    def test_dev_default_secret_outside_test_fails(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SESSION_SECRET", DEV_SESSION_SECRET_DEFAULT)
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            validate_startup_config()

    def test_strong_secret_outside_test_ok(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SESSION_SECRET", "a-strong-random-production-secret")
        validate_startup_config()  # must not raise

    def test_test_env_is_relaxed(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        validate_startup_config()  # must not raise


class TestSeedGating:
    def test_seed_allowed_in_test_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        assert seed_demo_operators_allowed() is True

    def test_seed_disabled_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("QC_SEED_DEMO_OPERATORS", raising=False)
        assert seed_demo_operators_allowed() is False

    def test_seed_opt_in_flag(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("QC_SEED_DEMO_OPERATORS", "true")
        assert seed_demo_operators_allowed() is True


class TestPasswordComparison:
    def test_correct_password_verifies(self):
        h = _make_password_hash("s3cret")
        assert _verify_password("s3cret", h) is True

    def test_wrong_password_rejected(self):
        h = _make_password_hash("s3cret")
        assert _verify_password("wrong", h) is False

    def test_malformed_hash_rejected(self):
        assert _verify_password("x", "not-a-valid-hash") is False
