"""Authentication and tenant authorization for external QC APIs.

Two credential shapes are accepted, both resolving to a :class:`Principal`:

* **Signed bearer tokens** — self-contained, HMAC-signed tokens minted by
  :func:`mint_token`. The tenant and admin flag are claims *inside* the signed
  payload, so a caller can never widen their own scope by editing a header.
* **Static API keys** — an operator-provisioned ``QC_API_KEYS`` env map of
  ``key -> {"tenant_id": ..., "admin": bool}`` for machine clients that cannot
  mint signed tokens.

The single source of truth for a request's tenant is the authenticated
principal. Routes must derive ``tenant_id`` from :attr:`Principal.tenant_id`
(via :meth:`Principal.resolve_tenant`) and never trust a caller-supplied
``tenant_id`` on protected routes.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from itsdangerous import BadSignature, URLSafeSerializer

# The known dev default that must never be used to sign real tokens / sessions.
DEV_SESSION_SECRET_DEFAULT = "dev-secret-change-in-prod"

_TOKEN_SALT = "qc-api-token-v1"
# Stable secret used only when running the test suite (APP_ENV=test) so tests
# can mint and verify tokens without provisioning real secrets.
_TEST_TOKEN_SECRET = "test-api-token-secret"


def _app_env() -> str:
    return os.getenv("APP_ENV", "production").lower()


def _token_secret() -> str:
    """Resolve the secret used to sign/verify bearer tokens.

    Precedence: ``API_TOKEN_SECRET`` → ``SESSION_SECRET`` → (test-only default).
    In non-test environments an unset/blank/dev-default secret is a hard error
    so tokens are never signed with a guessable key.
    """
    secret = os.getenv("API_TOKEN_SECRET") or os.getenv("SESSION_SECRET")
    if _app_env() == "test":
        return secret or _TEST_TOKEN_SECRET
    if not secret or secret == DEV_SESSION_SECRET_DEFAULT:
        raise RuntimeError(
            "API_TOKEN_SECRET or SESSION_SECRET must be set to a non-default value "
            "to sign API tokens outside the test environment."
        )
    return secret


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(_token_secret(), salt=_TOKEN_SALT)


@dataclass(frozen=True)
class Principal:
    """An authenticated caller. ``tenant_id`` is authoritative."""

    tenant_id: str
    subject: str
    is_admin: bool = False

    def resolve_tenant(self, requested: Optional[str]) -> str:
        """Return the authoritative tenant, rejecting a mismatched request value.

        Protected routes keep backward-compatible request models that may still
        carry ``tenant_id``. That field is only honored when it matches the
        principal; any other value is a cross-tenant attempt and is denied.
        """
        if requested is not None and requested != "" and requested != self.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="tenant_id does not match authenticated principal",
            )
        return self.tenant_id


def mint_token(tenant_id: str, subject: str = "api", is_admin: bool = False) -> str:
    """Create a signed bearer token carrying the tenant/admin claims."""
    payload = {"t": tenant_id, "s": subject, "a": bool(is_admin)}
    return _serializer().dumps(payload)


def _principal_from_token(token: str) -> Optional[Principal]:
    try:
        payload = _serializer().loads(token)
    except BadSignature:
        return None
    except Exception:
        return None
    tenant_id = payload.get("t")
    if not tenant_id:
        return None
    return Principal(
        tenant_id=tenant_id,
        subject=payload.get("s") or "api",
        is_admin=bool(payload.get("a")),
    )


@lru_cache(maxsize=1)
def _static_api_keys_cache(raw: str) -> dict:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _principal_from_api_key(key: str) -> Optional[Principal]:
    raw = os.getenv("QC_API_KEYS")
    if not raw:
        return None
    entry = _static_api_keys_cache(raw).get(key)
    if not entry or not isinstance(entry, dict):
        return None
    tenant_id = entry.get("tenant_id")
    if not tenant_id:
        return None
    return Principal(
        tenant_id=tenant_id,
        subject=entry.get("subject") or f"api-key:{key[:6]}",
        is_admin=bool(entry.get("admin")),
    )


def _extract_credential(
    authorization: Optional[str], x_api_key: Optional[str]
) -> Optional[Principal]:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            principal = _principal_from_token(value.strip())
            if principal is not None:
                return principal
            # A bearer value may also be a static API key.
            principal = _principal_from_api_key(value.strip())
            if principal is not None:
                return principal
    if x_api_key:
        return _principal_from_api_key(x_api_key.strip())
    return None


def require_principal(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Principal:
    """FastAPI dependency: resolve and require an authenticated principal.

    Anonymous or invalid credentials → ``401``.
    """
    principal = _extract_credential(authorization, x_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require_admin(principal: Principal = Depends(require_principal)) -> Principal:
    """FastAPI dependency: require an admin principal (401 → 403)."""
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return principal
