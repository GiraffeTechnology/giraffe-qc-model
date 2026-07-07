"""Tests for the Giraffe web shell — welcome / navigation / i18n / admin home (S1).

Maps to acceptance criteria in S1_WEB_SHELL_NAV_I18N.md:
  * Welcome page shows icon + both branches, no scroll needed.
  * Every admin page has the language-switch icon.
  * Device-language default respected; English fallback works; selection persists.
  * `/admin` is a usable home with 5 cards, not blank.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
from src.api.main import app
from src.api.deps import get_db_dep
from src.web.i18n import (
    LANGUAGE_COOKIE,
    device_language,
    normalize_language,
    resolve_language,
    translate,
)

# Scaffold routes that must exist and never 404/blank (§4.1).
SCAFFOLD_ROUTES = [
    "/admin",
    "/admin/studio",
    "/admin/samples",
    "/admin/workstations",
    "/admin/bundles",
    "/admin/results",
    "/admin/settings/language",
]


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def client(db_engine):
    factory = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_dep] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- Welcome page ----------------------------------------------------------


def test_welcome_shows_icon_and_both_branches(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    # Giraffe icon present.
    assert "🦒" in body
    # Both branches present and pointing at the right entrypoints.
    assert 'href="/admin"' in body
    assert 'href="/pad/login"' in body
    assert "welcome__branch--admin" in body
    assert "welcome__branch--operator" in body
    # Language switch present on the welcome page.
    assert "lang-switch" in body


# --- Admin home ------------------------------------------------------------


def test_admin_home_has_five_cards(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    body = resp.text
    # Five cards, not a blank redirect.
    assert body.count('class="card"') == 5
    # All five destinations are linked.
    for href in ["/admin/studio", "/admin/samples", "/admin/workstations",
                 "/admin/bundles", "/admin/results"]:
        assert f'href="{href}"' in body


def test_admin_home_shows_sample_count_where_available(client):
    resp = client.get("/admin")
    # Samples card exposes a count element (available via the SKU store).
    assert "card__count" in resp.text


# --- Scaffold routes -------------------------------------------------------


@pytest.mark.parametrize("route", SCAFFOLD_ROUTES)
def test_scaffold_route_is_not_404_or_blank(client, route):
    resp = client.get(route)
    assert resp.status_code == 200, route
    assert len(resp.text.strip()) > 200, route


@pytest.mark.parametrize("route", SCAFFOLD_ROUTES)
def test_every_admin_page_has_language_switch(client, route):
    resp = client.get(route)
    assert "lang-switch" in resp.text, route
    assert "🌐" in resp.text, route


# --- i18n unit behaviour ---------------------------------------------------


def test_normalize_language_maps_variants():
    assert normalize_language("en-US") == "en"
    assert normalize_language("zh") == "zh-CN"
    assert normalize_language("zh-Hans") == "zh-CN"
    assert normalize_language("zh-TW") == "zh-CN"
    assert normalize_language("ja-JP") == "ja"
    assert normalize_language("fr") is None
    assert normalize_language("") is None
    assert normalize_language(None) is None


def test_device_language_respects_quality_and_fallback():
    # Highest-q supported language wins.
    assert device_language("fr;q=0.9, ja;q=0.8, en;q=0.5") == "ja"
    # Unsupported primary is skipped; next supported one is used.
    assert device_language("fr-FR, zh-CN") == "zh-CN"
    # No supported language -> None (caller applies English fallback).
    assert device_language("fr-FR, de") is None
    assert device_language(None) is None


# --- i18n end-to-end resolution -------------------------------------------


def test_device_language_default_respected(client):
    resp = client.get("/admin", headers={"Accept-Language": "ja"})
    assert resp.status_code == 200
    # Japanese admin-home title appears.
    assert translate("admin.home.title", "ja") in resp.text
    # <html lang> reflects the resolved language.
    assert '<html lang="ja">' in resp.text


def test_english_fallback_for_unsupported_device_language(client):
    resp = client.get("/admin", headers={"Accept-Language": "fr-FR,de;q=0.8"})
    assert '<html lang="en">' in resp.text
    assert translate("admin.home.title", "en") in resp.text


def test_selection_persists_and_overrides_device_language(client):
    # Set an explicit selection; server should persist it via cookie.
    resp = client.post(
        "/admin/settings/language",
        data={"language": "zh-CN", "next": "/admin"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"
    assert LANGUAGE_COOKIE in resp.cookies
    assert resp.cookies[LANGUAGE_COOKIE] == "zh-CN"

    # TestClient keeps the cookie jar: a later request with a *different*
    # device language must still render Chinese (persisted selection wins).
    followup = client.get("/admin", headers={"Accept-Language": "ja"})
    assert '<html lang="zh-CN">' in followup.text
    assert translate("admin.home.title", "zh-CN") in followup.text


def test_admin_studio_uses_persisted_language_for_static_and_js_copy(client):
    client.cookies.set(LANGUAGE_COOKIE, "zh-CN")
    resp = client.get("/admin/studio", headers={"Accept-Language": "en"})
    assert resp.status_code == 200
    body = resp.text
    assert '<html lang="zh-CN">' in body
    assert translate("studio.header.title", "zh-CN") in body
    assert translate("studio.search.placeholder", "zh-CN") in body
    assert translate("studio.empty.standard", "zh-CN") in body
    assert "welcome:" in body
    # Jinja's tojson safely escapes non-ASCII text in the injected JS payload.
    assert "\\u6b22\\u8fce\\u8fdb\\u5165\\u7ba1\\u7406\\u5de5\\u4f5c\\u5ba4" in body
    assert "Admin Studio" not in body
    assert "Create a SKU or describe QC requirements" not in body


def test_set_language_guards_against_open_redirect(client):
    resp = client.post(
        "/admin/settings/language",
        data={"language": "en", "next": "//evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"


def test_resolve_language_prefers_cookie_over_device(client):
    # Sanity at the unit level using a lightweight fake request.
    class _Req:
        def __init__(self, cookies, accept):
            self.cookies = cookies
            self.headers = {"accept-language": accept} if accept else {}
            self.session = {}

    assert resolve_language(_Req({LANGUAGE_COOKIE: "ja"}, "en-US")) == "ja"
    assert resolve_language(_Req({}, "zh-CN")) == "zh-CN"
    assert resolve_language(_Req({}, "fr")) == "en"
