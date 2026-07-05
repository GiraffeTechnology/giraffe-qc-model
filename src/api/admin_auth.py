"""Session-based authentication for the server-rendered /admin surface.

The Sample Admin and Configuration UI are browser tools for QC engineers, so
they authenticate with a signed cookie session (via Starlette
``SessionMiddleware``) rather than bearer tokens. The authenticated operator's
tenant is authoritative — admin pages never trust a caller-supplied
``tenant_id``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request, status

from src.db.pad_models import QCOperatorProfile

# Roles permitted to use the configuration / sample-admin UI.
ADMIN_ROLES = {"admin", "engineer"}

_SESSION_KEY_OPERATOR = "admin_operator_id"
_SESSION_KEY_TENANT = "admin_tenant_id"
_SESSION_KEY_ROLE = "admin_role"
_SESSION_KEY_USERNAME = "admin_username"


@dataclass(frozen=True)
class AdminSession:
    operator_id: int
    tenant_id: str
    username: str
    role: str


def login_admin(request: Request, operator: QCOperatorProfile) -> None:
    request.session[_SESSION_KEY_OPERATOR] = str(operator.id)
    request.session[_SESSION_KEY_TENANT] = operator.tenant_id
    request.session[_SESSION_KEY_ROLE] = operator.role
    request.session[_SESSION_KEY_USERNAME] = operator.username


def logout_admin(request: Request) -> None:
    for key in (
        _SESSION_KEY_OPERATOR,
        _SESSION_KEY_TENANT,
        _SESSION_KEY_ROLE,
        _SESSION_KEY_USERNAME,
    ):
        request.session.pop(key, None)


def current_admin(request: Request) -> Optional[AdminSession]:
    """Return the logged-in admin session, or ``None`` if unauthenticated."""
    operator_id = request.session.get(_SESSION_KEY_OPERATOR)
    tenant_id = request.session.get(_SESSION_KEY_TENANT)
    role = request.session.get(_SESSION_KEY_ROLE)
    username = request.session.get(_SESSION_KEY_USERNAME)
    if not operator_id or not tenant_id or role not in ADMIN_ROLES:
        return None
    try:
        return AdminSession(
            operator_id=int(operator_id),
            tenant_id=tenant_id,
            username=username or "",
            role=role,
        )
    except (TypeError, ValueError):
        return None


def require_admin_session(request: Request) -> AdminSession:
    """Dependency for admin mutations/JSON: 401 when unauthenticated.

    HTML GET pages should call :func:`current_admin` and redirect to the login
    page instead of raising, for a usable browser flow.
    """
    admin = current_admin(request)
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
        )
    return admin


def is_admin_role(role: str) -> bool:
    return role in ADMIN_ROLES
