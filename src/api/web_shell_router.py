"""FastAPI router for the Giraffe web shell (Session S1).

Owns the routing shell, welcome page, `/admin` home and the language-switch /
language-settings surface. Feature sessions (S2-S4) own the internals of the
Studio / Workstations / Bundles / Results pages; this router only guarantees
those routes exist, render a non-blank scaffold, and carry the language switch.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.db.sku_models import QCSkuItem
from src.web.i18n import (
    DEFAULT_LANGUAGE,
    install_i18n,
    normalize_language,
    persist_language,
)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_i18n(templates)

router = APIRouter(tags=["shell"])


def _render(request: Request, template: str, **context) -> HTMLResponse:
    """Render a shell template; i18n globals are injected via install_i18n."""
    return templates.TemplateResponse(request, template, context=context)


def _active_sample_count(db: Session) -> Optional[int]:
    """Best-effort active-sample count for the home card; ``None`` if unavailable."""
    try:
        return (
            db.query(QCSkuItem)
            .filter(QCSkuItem.tenant_id == "default", QCSkuItem.status == "active")
            .count()
        )
    except Exception:
        return None


# --- Welcome ---------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def welcome(request: Request):
    """Welcome page: Giraffe icon, Administrator / Operator branches, language switch."""
    return _render(request, "welcome.html")


# --- Admin home ------------------------------------------------------------


@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, db: Session = Depends(get_db_dep)):
    """`/admin` home: five cards, each with description and (where available) a count."""
    cards = [
        {
            "href": "/admin/studio",
            "icon": "🎬",
            "title_key": "admin.card.studio.title",
            "desc_key": "admin.card.studio.desc",
            "count": None,
            "count_label_key": None,
        },
        {
            "href": "/admin/samples",
            "icon": "🧩",
            "title_key": "admin.card.samples.title",
            "desc_key": "admin.card.samples.desc",
            "count": _active_sample_count(db),
            "count_label_key": "admin.card.samples.count_label",
        },
        {
            "href": "/admin/workstations",
            "icon": "🖥️",
            "title_key": "admin.card.workstations.title",
            "desc_key": "admin.card.workstations.desc",
            "count": None,
            "count_label_key": None,
        },
        {
            "href": "/admin/bundles",
            "icon": "📦",
            "title_key": "admin.card.bundles.title",
            "desc_key": "admin.card.bundles.desc",
            "count": None,
            "count_label_key": None,
        },
        {
            "href": "/admin/results",
            "icon": "📊",
            "title_key": "admin.card.results.title",
            "desc_key": "admin.card.results.desc",
            "count": None,
            "count_label_key": None,
        },
    ]
    return _render(request, "admin_home.html", cards=cards)


# --- Feature routes formerly scaffolded here (S2-S4) -----------------------
#
# The shell scaffold used to render placeholder pages here so navigation never
# 404'd before the feature sessions landed. All of them have now landed and own
# their real routes, each carrying the shared language switch via base.html:
#   * /admin/studio          — S2, qc_studio_router
#   * /admin/bundles         — S3, qc_bundle_router
#   * /admin/workstations    — S3, qc_bundle_router
#   * /admin/results         — S4, qc_verdict_router
# so no stub routes remain.


# --- Language settings -----------------------------------------------------


@router.get("/admin/settings/language", response_class=HTMLResponse)
def language_settings(request: Request):
    return _render(request, "language_settings.html")


@router.post("/admin/settings/language")
def set_language(
    request: Request,
    language: str = Form(...),
    next: str = Form(default="/admin"),
):
    """Persist an explicit language selection and return to the originating page."""
    resolved = normalize_language(language) or DEFAULT_LANGUAGE
    # Guard against open redirects: only allow local, non-protocol-relative paths.
    target = next if next.startswith("/") and not next.startswith("//") else "/admin"
    response = RedirectResponse(target, status_code=303)
    persist_language(response, resolved)
    try:
        request.session["lang"] = resolved
    except (AssertionError, AttributeError):
        pass
    return response
