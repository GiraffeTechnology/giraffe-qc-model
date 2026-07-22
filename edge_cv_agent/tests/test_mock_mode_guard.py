"""Mock CV must never be selectable in a production deployment."""
from __future__ import annotations

import pytest

from edge_cv_agent.app.config import AgentConfig, MockModeNotAllowedInProduction


def test_default_is_mock_outside_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("EDGE_AGENT_MOCK_MODE", raising=False)
    assert AgentConfig().mock_mode is True


def test_production_refuses_default_mock(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EDGE_AGENT_MOCK_MODE", raising=False)
    with pytest.raises(MockModeNotAllowedInProduction):
        AgentConfig()


def test_production_refuses_explicit_mock(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EDGE_AGENT_MOCK_MODE", "true")
    with pytest.raises(MockModeNotAllowedInProduction):
        AgentConfig()


def test_production_with_explicit_real_mode_starts(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EDGE_AGENT_MOCK_MODE", "false")
    assert AgentConfig().mock_mode is False
