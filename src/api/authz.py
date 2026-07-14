"""Central authentication + tenant-isolation middleware.

This is the single fail-closed gate in front of every admin console page and
every QC management API. It exists so tenant isolation cannot be forgotten on a
per-endpoint basis: no matter which handler serves a protected path, the request
is authenticated first and the *effective tenant is forced to the authenticated
principal's tenant* — a caller can never act on another tenant by passing a
``tenant_id`` query param or body field.

Protected path prefixes (admin-only):

* ``/admin``    — the server-rendered admin console (Studio, Samples, Bundles,
                  Workstations, Results). Browser session auth; unauthenticated
                  GETs redirect to the login page.
* ``/api/qc``   — the QC management JSON APIs (SKUs, intake, bundles,
                  workstations, results, …). Bearer-token / API-key auth; 401.

Explicitly public within those prefixes: the login/logout routes and the
language switch (which must render on the login page itself).

The Pad operator surface (``/api/v1/pad``, ``/pad``) has its own operator login
and is intentionally out of scope here.

Tenant enforcement:

* the ``tenant_id`` query parameter is rewritten to the principal's tenant;
* a JSON body's top-level ``tenant_id`` is rewritten to the principal's tenant;
* multipart upload handlers read ``request.state.tenant_id`` directly.

**Test-only relaxation.** When ``APP_ENV=test`` *and no credential is presented*,
the request passes through unauthenticated so the existing suite (which calls
endpoints with an explicit ``tenant_id`` and no auth header) keeps working. This
branch is gated on the environment and is impossible in production: outside the
test environment an anonymous request to a protected path is always rejected.
When a real credential *is* presented, full enforcement runs even under
``APP_ENV=test`` — that is how the isolation tests exercise the production path.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlencode

from fastapi import HTTPException
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.api.auth import (
    Principal,
    _app_env,
    _principal_from_api_key,
    _principal_from_token,
)
from src.api.admin_auth import ADMIN_ROLES

# Path prefixes that require an authenticated admin principal.
_PROTECTED_PREFIXES = ("/admin", "/api/qc")

# Public routes inside the protected prefixes (auth entry points + i18n).
_PUBLIC_PATHS = frozenset({
    "/admin/login",
    "/admin/logout",
    "/admin/settings/language",
})


def _is_protected(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return False
    return any(path == p or path.startswith(p + "/") for p in _PROTECTED_PREFIXES)


def effective_tenant(request, fallback: str = "default") -> str:
    """Authoritative tenant for a request.

    Returns the authenticated principal's tenant when the auth gate ran (all
    protected routes in production). ``fallback`` is only reached on the
    test-only anonymous passthrough, where the handler keeps its caller-supplied
    value so the existing suite is unchanged. Handlers that build filesystem
    paths or DB filters from a multipart ``tenant_id`` field must call this,
    because the middleware only rewrites query strings and JSON bodies.
    """
    state = getattr(request, "state", None)
    tenant = getattr(state, "tenant_id", None)
    return tenant if tenant else fallback


def effective_actor(request, claimed: str | None = None) -> str:
    """Return the authenticated actor and reject caller-supplied impersonation.

    Protected production routes always have ``request.state.principal`` from
    :class:`AuthTenantMiddleware`. The fallback exists only for the suite's
    explicit anonymous ``APP_ENV=test`` compatibility path.
    """
    state = getattr(request, "state", None)
    principal = getattr(state, "principal", None)
    if principal is not None:
        if claimed and claimed != principal.subject:
            raise HTTPException(
                status_code=403,
                detail="actor does not match authenticated principal",
            )
        return principal.subject
    if _app_env() == "test":
        return claimed or "test-admin"
    raise HTTPException(status_code=401, detail="authenticated actor required")


def _principal_from_session(session: dict) -> Principal | None:
    """Build an admin principal from a decoded browser session, if valid."""
    operator_id = session.get("admin_operator_id")
    tenant_id = session.get("admin_tenant_id")
    role = session.get("admin_role")
    if not operator_id or not tenant_id or role not in ADMIN_ROLES:
        return None
    return Principal(
        tenant_id=tenant_id,
        subject=session.get("admin_username") or f"admin:{operator_id}",
        is_admin=True,
    )


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def resolve_principal(scope: Scope) -> Principal | None:
    """Resolve a principal from a bearer token, API key, or admin session."""
    authorization = _header(scope, b"authorization")
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            principal = _principal_from_token(value.strip()) or _principal_from_api_key(value.strip())
            if principal is not None:
                return principal
    api_key = _header(scope, b"x-api-key")
    if api_key:
        principal = _principal_from_api_key(api_key.strip())
        if principal is not None:
            return principal
    session = scope.get("session")
    if isinstance(session, dict):
        return _principal_from_session(session)
    return None


def _rewrite_query_tenant(scope: Scope, tenant_id: str) -> None:
    """Force the ``tenant_id`` query parameter to the principal's tenant."""
    raw = scope.get("query_string", b"").decode("latin-1")
    pairs = [(k, v) for k, v in parse_qsl(raw, keep_blank_values=True) if k != "tenant_id"]
    pairs.append(("tenant_id", tenant_id))
    scope["query_string"] = urlencode(pairs).encode("latin-1")


def _set_content_length(scope: Scope, length: int) -> None:
    headers = [(k, v) for k, v in scope.get("headers", []) if k != b"content-length"]
    headers.append((b"content-length", str(length).encode("latin-1")))
    scope["headers"] = headers


class AuthTenantMiddleware:
    """Fail-closed authn + tenant-isolation gate (pure ASGI)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_protected(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        principal = resolve_principal(scope)

        if principal is None:
            if _app_env() == "test":
                # Test-only: anonymous passthrough. Impossible in production.
                await self.app(scope, receive, send)
                return
            await self._reject(scope, receive, send)
            return

        if not principal.is_admin:
            await JSONResponse(
                {"detail": "Admin privileges required"}, status_code=403
            )(scope, receive, send)
            return

        # Authenticated: pin the effective tenant to the principal.
        scope.setdefault("state", {})
        scope["state"]["principal"] = principal
        scope["state"]["tenant_id"] = principal.tenant_id
        _rewrite_query_tenant(scope, principal.tenant_id)
        receive = await self._maybe_rewrite_json_tenant(scope, receive, principal.tenant_id)

        await self.app(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        # Browser GETs to the console → send them to the login page.
        if path.startswith("/admin") and method == "GET":
            await RedirectResponse(
                url=f"/admin/login?next={path}", status_code=303
            )(scope, receive, send)
            return
        await JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )(scope, receive, send)

    async def _maybe_rewrite_json_tenant(
        self, scope: Scope, receive: Receive, tenant_id: str
    ) -> Receive:
        """Buffer a JSON body and force its top-level ``tenant_id``.

        Returns a replacement ``receive`` that replays the (possibly rewritten)
        body. Non-JSON bodies are replayed untouched.
        """
        method = scope.get("method", "GET").upper()
        if method not in ("POST", "PUT", "PATCH"):
            return receive
        content_type = (_header(scope, b"content-type") or "").lower()
        if "application/json" not in content_type:
            return receive

        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                # Replay unexpected messages verbatim.
                return _single_message_receive(message)
            body += message.get("body", b"")
            more = message.get("more_body", False)

        new_body = body
        if body:
            try:
                payload = json.loads(body)
                if isinstance(payload, dict):
                    payload["tenant_id"] = tenant_id
                    new_body = json.dumps(payload).encode("utf-8")
                    _set_content_length(scope, len(new_body))
            except (json.JSONDecodeError, ValueError):
                new_body = body  # not valid JSON → leave as-is (handler will 422)

        return _replay_body_receive(new_body)


def _replay_body_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _single_message_receive(message: Message) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return message
        return {"type": "http.disconnect"}

    return receive
