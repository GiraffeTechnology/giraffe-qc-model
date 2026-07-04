"""Admin console login / logout (browser session auth).

These routes are the only unauthenticated entry points under ``/admin`` (see
``authz._PUBLIC_PATHS``). A successful sign-in stores the operator's tenant and
role in the signed cookie session; every other ``/admin`` page then resolves its
tenant from that session, never from a caller-supplied field.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.api.admin_auth import is_admin_role, login_admin, logout_admin
from src.api.deps import get_db_dep
from src.pad.session_service import authenticate_operator
from src.web.i18n import install_i18n

router = APIRouter(tags=["admin-auth"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_i18n(templates)


def _safe_next(next_path: str | None) -> str:
    """Only allow local, non-protocol-relative redirect targets."""
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/admin"


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/admin"):
    return templates.TemplateResponse(
        request, "admin_login.html", {"error": None, "next": _safe_next(next)}
    )


@router.post("/admin/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    tenant_id: str = Form("demo"),
    next: str = Form("/admin"),
    db: Session = Depends(get_db_dep),
):
    operator = authenticate_operator(db, username, password, tenant_id)
    if operator is None or not is_admin_role(operator.role):
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            {"error": "Invalid credentials or insufficient role", "next": _safe_next(next)},
            status_code=401,
        )
    login_admin(request, operator)
    return RedirectResponse(url=_safe_next(next), status_code=303)


@router.get("/admin/logout")
def logout(request: Request):
    logout_admin(request)
    return RedirectResponse(url="/admin/login", status_code=303)
