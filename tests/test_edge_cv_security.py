"""Device-registration bootstrap-token gate (§17.2)."""
from __future__ import annotations

from tests.edge_cv_helpers import db_session, client  # noqa: F401


def _register(client, headers=None):
    return client.post(
        "/api/edge-cv/devices/register",
        json={"device_name": "jetson-x", "device_type": "jetson_nano_2gb", "capabilities": ["opencv"]},
        headers=headers or {},
    )


def test_register_allowed_without_secret_in_test_env(client):
    # APP_ENV=test → insecure registration allowed so the suite needs no secret.
    assert _register(client).status_code == 201


def test_register_requires_correct_bootstrap_token_when_secret_set(client, monkeypatch):
    monkeypatch.setenv("EDGE_CV_REGISTRATION_SECRET", "s3cret-bootstrap")
    # Missing header → 401.
    assert _register(client).status_code == 401
    # Wrong token → 401.
    assert _register(client, {"X-Edge-CV-Bootstrap-Token": "nope"}).status_code == 401
    # Correct token → 201.
    assert _register(client, {"X-Edge-CV-Bootstrap-Token": "s3cret-bootstrap"}).status_code == 201


def test_bootstrap_token_alias_env_var(client, monkeypatch):
    monkeypatch.setenv("EDGE_CV_BOOTSTRAP_TOKEN", "alias-secret")
    assert _register(client).status_code == 401
    assert _register(client, {"X-Edge-CV-Bootstrap-Token": "alias-secret"}).status_code == 201


def test_register_rejected_in_production_without_secret(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EDGE_CV_REGISTRATION_SECRET", raising=False)
    monkeypatch.delenv("EDGE_CV_BOOTSTRAP_TOKEN", raising=False)
    monkeypatch.delenv("EDGE_CV_ALLOW_INSECURE_REGISTRATION", raising=False)
    assert _register(client).status_code == 401


def test_register_explicit_insecure_mode_in_production(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EDGE_CV_REGISTRATION_SECRET", raising=False)
    monkeypatch.setenv("EDGE_CV_ALLOW_INSECURE_REGISTRATION", "true")
    # Production still needs a token-signing secret to mint the device token.
    monkeypatch.setenv("API_TOKEN_SECRET", "prod-token-secret")
    assert _register(client).status_code == 201
