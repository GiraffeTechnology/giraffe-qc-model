"""Service-issued device tokens for the Edge CV agent APIs (§17.2).

A device token is an HMAC-signed, self-contained bearer token minted at
registration time. It carries the ``device_id`` and ``session_id`` as signed
claims, so an agent cannot widen its scope or impersonate another device/session
by editing the token — a forged or stale-signature token fails verification.

The signing secret is resolved with the same precedence as the rest of the repo
(``API_TOKEN_SECRET`` → ``SESSION_SECRET`` → a test-only default under
``APP_ENV=test``) so no new secret has to be provisioned. No real token is ever
committed.
"""
from __future__ import annotations

from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer

from src.api.auth import _token_secret

_DEVICE_TOKEN_SALT = "edge-cv-device-token-v1"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(_token_secret(), salt=_DEVICE_TOKEN_SALT)


def mint_device_token(device_id: str, session_id: str, tenant_id: str = "default") -> str:
    """Create a signed device token bound to a device + session + tenant."""
    return _serializer().dumps({"d": device_id, "s": session_id, "t": tenant_id})


def verify_device_token(token: str) -> Optional[dict]:
    """Return the token claims ``{device_id, session_id, tenant_id}`` or None.

    ``None`` on any bad/forged/malformed token.
    """
    try:
        payload = _serializer().loads(token)
    except BadSignature:
        return None
    except Exception:
        return None
    device_id = payload.get("d")
    session_id = payload.get("s")
    if not device_id or not session_id:
        return None
    return {
        "device_id": device_id,
        "session_id": session_id,
        "tenant_id": payload.get("t") or "default",
    }
