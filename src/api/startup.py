"""Startup configuration validation.

Fails fast (clear error) when required secrets are missing or left at a known
insecure default in a non-test environment. Keeps secret values out of logs.
"""
from __future__ import annotations

import logging
import os

from src.api.auth import DEV_SESSION_SECRET_DEFAULT

logger = logging.getLogger(__name__)


def _app_env() -> str:
    return os.getenv("APP_ENV", "production").lower()


def _mask(value: str | None) -> str:
    if not value:
        return "<unset>"
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


# Stable secret used only under APP_ENV=test so the suite can sign cookie
# sessions without provisioning a production secret.
_TEST_SESSION_SECRET = "test-session-secret"


def session_secret() -> str:
    """Return the cookie-session signing secret.

    Test env → a stable test-only secret. Otherwise the configured
    ``SESSION_SECRET`` is required and must not be the dev default; an unset or
    dev-default secret is a hard error so sessions are never signed with a
    guessable key. (``validate_startup_config`` re-checks this at boot, but
    resolving it here means even an app constructed without lifespan cannot fall
    back to the dev default in production.)
    """
    secret = os.getenv("SESSION_SECRET")
    if _app_env() == "test":
        return secret or _TEST_SESSION_SECRET
    if not secret or secret == DEV_SESSION_SECRET_DEFAULT:
        raise RuntimeError(
            "SESSION_SECRET must be set to a strong, non-default value before "
            "starting outside the test environment."
        )
    return secret


def validate_startup_config() -> None:
    """Validate required runtime configuration. Raises RuntimeError on failure.

    In the test environment validation is relaxed so the suite can run without
    provisioning production secrets.
    """
    env = _app_env()
    if env == "test":
        return

    session_secret = os.getenv("SESSION_SECRET")
    if not session_secret or session_secret == DEV_SESSION_SECRET_DEFAULT:
        raise RuntimeError(
            "SESSION_SECRET must be set to a strong, non-default value before "
            "starting outside the test environment. Refusing to start with an "
            f"unset or dev-default session secret (got {_mask(session_secret)})."
        )

    logger.info(
        "Startup config validated (env=%s, session_secret=%s)",
        env,
        _mask(session_secret),
    )
