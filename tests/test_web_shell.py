"""Tests for the Giraffe web shell — welcome / navigation / i18n / admin home (S1).

Maps to acceptance criteria in S1_WEB_SHELL_NAV_I18N.md:
  * Welcome page shows icon + both branches, no scroll needed.
  * Every admin page has the language-switch icon.
  * Device-language default respected; English fallback works; selection persists.
  * `/admin` is a usable home with 5 cards, not blank.
"""
from __future__ import annotations

import json

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
    # Brand icon asset present (replaces the old 🦒 emoji).
    assert "🦒" not in body
    assert 'src="/static/giraffe-qc-model-icon.png"' in body
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


def test_admin_home_samples_card_precedes_studio_card(client):
    """UI audit (2026-07-22, PRD §9.8): samples-and-standards must come
    before the digital QC studio — there is nothing to train on until a
    sample has been captured and reviewed."""
    resp = client.get("/admin")
    body = resp.text
    assert body.index('href="/admin/samples"') < body.index('href="/admin/studio"')


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
    assert "bundleNote:" in body
    # Jinja's tojson safely escapes the complete localized bundle-note copy in
    # the injected JS payload (copy can evolve with the Studio product design).
    expected_bundle_note = json.dumps(
        translate("studio.js.bundle_note", "zh-CN"), ensure_ascii=True
    )[1:-1]
    assert expected_bundle_note in body
    assert "Admin Studio" not in body
    assert "Create a SKU or describe QC requirements" not in body


@pytest.mark.parametrize("lang", ["en", "zh-CN", "ja"])
def test_admin_studio_ws7_controls_have_complete_locale_payload(client, lang):
    # WS6 (region annotation, CV config) moved to the sample page (2026-07-22
    # workflow correction); Studio only retains WS7 (probation/qualification).
    client.cookies.set(LANGUAGE_COOKIE, lang)
    body = client.get("/admin/studio").text
    required = [
        "studio.js.probation_active", "studio.js.disagreement_report",
        "studio.standard_status.standard_active",
    ]
    for key in required:
        expected = translate(key, lang)
        assert expected != key
        # Static labels render directly; JS strings are JSON escaped.
        assert expected in body or json.dumps(expected, ensure_ascii=True)[1:-1] in body


@pytest.mark.parametrize("lang", ["en", "zh-CN", "ja"])
def test_sample_page_ws6_controls_have_complete_locale_payload(client, lang):
    created = client.post(
        "/admin/samples",
        follow_redirects=False,
        data={"tenant_id": "demo", "item_number": f"WS6-{lang}", "name": "WS6 locale"},
    )
    client.cookies.set(LANGUAGE_COOKIE, lang)
    body = client.get(created.headers["location"]).text
    required = [
        "studio.region.photo", "studio.region.save", "studio.js.add_regions",
        "studio.js.add_cv_config", "studio.js.regions_saved",
    ]
    for key in required:
        expected = translate(key, lang)
        assert expected != key
        assert expected in body or json.dumps(expected, ensure_ascii=True)[1:-1] in body


def test_admin_studio_status_filter_uses_prd_lifecycle_states(client):
    from src.db.sku_models import SKU_LIFECYCLE_STATES

    client.cookies.clear()  # isolate from language cookies set by other tests
    resp = client.get("/admin/studio")
    body = resp.text
    for state in SKU_LIFECYCLE_STATES:
        assert f'value="{state}"' in body, state
        assert translate(f"studio.status.{state}", "en") in body, state
    # Legacy statuses are no longer offered by the filter.
    for legacy in ("active", "inactive", "archived"):
        assert f'<option value="{legacy}">' not in body, legacy


def test_admin_login_page_i18n(client):
    client.cookies.set(LANGUAGE_COOKIE, "zh-CN")
    resp = client.get("/admin/login")
    body = resp.text
    assert '<html lang="zh-CN">' in body
    assert translate("admin.login.heading", "zh-CN") in body
    assert translate("admin.login.username", "zh-CN") in body
    assert translate("admin.login.submit", "zh-CN") in body
    assert "lang-switch" in body  # global language switch present
    assert "Admin sign in" not in body


def test_pad_login_page_i18n(client):
    for lang in ("en", "zh-CN", "ja"):
        client.cookies.set(LANGUAGE_COOKIE, lang)
        resp = client.get("/pad/login")
        body = resp.text
        assert f'<html lang="{lang}">' in body
        assert translate("pad.login.subtitle", lang) in body
        assert translate("pad.login.username", lang) in body
        assert translate("pad.login.submit", lang) in body
        assert translate("pad.orientation", lang) in body
        assert "lang-switch" in body
    client.cookies.set(LANGUAGE_COOKIE, "zh-CN")
    body = client.get("/pad/login").text
    assert "Factory Quality Control" not in body
    assert "Please rotate your device" not in body


def _pad_login(client):
    # seed_demo_operators runs inside the login POST; password == username.
    resp = client.post(
        "/pad/login",
        data={"username": "operator_en", "password": "operator_en", "tenant_id": "demo"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_pad_workspace_inspection_report_i18n(client):
    _pad_login(client)
    client.cookies.set(LANGUAGE_COOKIE, "zh-CN")

    body = client.get("/pad").text
    assert '<html lang="zh-CN">' in body
    assert translate("pad.workspace.chat_placeholder", "zh-CN") in body
    assert translate("pad.workspace.send", "zh-CN") in body
    assert translate("pad.workspace.cards_placeholder", "zh-CN") in body
    assert "GIRAFFE_PAD_I18N" in body
    assert "Type your message" not in body
    assert "Action cards will appear here" not in body

    body = client.get("/pad/inspections/1").text
    assert '<html lang="zh-CN">' in body
    assert translate("pad.inspection.checkpoints", "zh-CN") in body
    assert translate("pad.inspection.submit", "zh-CN") in body
    assert translate("pad.inspection.heading", "zh-CN").format(id=1) in body
    assert "Submit Results" not in body

    body = client.get("/pad/inspections/1/report").text
    assert '<html lang="zh-CN">' in body
    assert translate("pad.report.summary", "zh-CN") in body
    assert translate("pad.report.legend.pass", "zh-CN") in body
    assert translate("pad.report.heading", "zh-CN").format(id=1) in body
    assert "Report Summary" not in body


def test_pad_language_api_syncs_shell_cookie(client):
    client.cookies.clear()  # isolate from language cookies set by other tests
    _pad_login(client)
    resp = client.post("/api/v1/pad/language", json={"language": "ja"})
    assert resp.status_code == 200
    assert resp.cookies.get(LANGUAGE_COOKIE) == "ja"
    # Page chrome follows the operator's preference after reload.
    assert '<html lang="ja">' in client.get("/pad").text


def test_pad_login_invalid_error_is_localized(client):
    client.cookies.set(LANGUAGE_COOKIE, "ja")
    resp = client.post(
        "/pad/login",
        data={"username": "nobody", "password": "wrong", "tenant_id": "demo"},
    )
    assert resp.status_code == 401
    assert translate("pad.login.invalid", "ja") in resp.text
    assert "Invalid credentials" not in resp.text


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
