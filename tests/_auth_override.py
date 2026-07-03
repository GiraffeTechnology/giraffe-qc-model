"""Test helpers for the API auth layer.

Two modes are used across the suite:

* ``install_api_auth_override(app)`` — replaces ``require_principal`` with a
  trusting principal that derives the tenant from the request the same way the
  pre-auth API did (query/body ``tenant_id``). This keeps the large body of
  *functional* tests exercising business logic without threading tokens through
  every request. Real authentication (401 / cross-tenant / token) is covered by
  the dedicated tests in ``test_api_authz.py``, which do NOT install this
  override.

* ``auth_headers(tenant_id)`` / ``mint_token`` — mint a real signed token for
  tests that assert on the genuine auth behavior.
"""
from __future__ import annotations

from fastapi import Request

from src.api.auth import Principal, mint_token, require_principal


class _TrustingPrincipal(Principal):
    """Principal that trusts a caller-supplied tenant (test override only)."""

    def resolve_tenant(self, requested):  # type: ignore[override]
        if requested is not None and requested != "":
            return requested
        return self.tenant_id


def _principal_from_request(request: Request) -> Principal:
    tenant = request.query_params.get("tenant_id") or "default"
    return _TrustingPrincipal(tenant_id=tenant, subject="test", is_admin=True)


def install_api_auth_override(app) -> None:
    app.dependency_overrides[require_principal] = _principal_from_request


def auth_headers(tenant_id: str, is_admin: bool = False) -> dict:
    return {"Authorization": f"Bearer {mint_token(tenant_id, is_admin=is_admin)}"}


__all__ = [
    "install_api_auth_override",
    "auth_headers",
    "mint_token",
]
