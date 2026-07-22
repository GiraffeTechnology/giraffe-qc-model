"""Tests for the shared QC Sample Admin UI."""
from __future__ import annotations

import io
import re

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
from src.web.i18n import LANGUAGE_COOKIE, translate

TENANT = "default"


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
def db_session_factory(db_engine):
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def client(db_session_factory):
    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_dep] = override_get_db
    with TestClient(app, follow_redirects=True) as c:
        yield c
    app.dependency_overrides.clear()


def _make_sku(client, item_number: str, name: str) -> str:
    """Create a sample via admin UI and return its sku_id."""
    client.post("/admin/samples", data={
        "tenant_id": TENANT,
        "item_number": item_number,
        "name": name,
    })
    resp = client.get("/api/v1/sku/search", params={"q": item_number, "tenant_id": TENANT})
    items = resp.json()["items"]
    return items[0]["id"] if items else ""


def _tiny_png() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c49444154789c62f80f00000101000518d84e0000000049454e44ae426082"
    )


# ─── List page ──────────────────────────────────────────────────────────────


class TestAdminListPage:
    def test_list_returns_200(self, client):
        resp = client.get("/admin/samples")
        assert resp.status_code == 200

    def test_list_contains_generic_title(self, client):
        resp = client.get("/admin/samples")
        assert "QC Sample Admin" in resp.text

    def test_list_not_android_specific(self, client):
        resp = client.get("/admin/samples")
        assert "Android Pad Sample Admin" not in resp.text
        assert "Pad Sample Manager" not in resp.text

    def test_list_is_html(self, client):
        resp = client.get("/admin/samples")
        assert "text/html" in resp.headers.get("content-type", "")


# ─── New page ──────────────────────────────────────────────────────────────


class TestAdminNewPage:
    def test_new_returns_200(self, client):
        resp = client.get("/admin/samples/new")
        assert resp.status_code == 200

    def test_new_contains_form_fields(self, client):
        resp = client.get("/admin/samples/new")
        assert "item_number" in resp.text
        assert "name" in resp.text


# ─── Create sample ───────────────────────────────────────────────────────────


class TestAdminCreateSku:
    def test_create_sku_shows_detail_page(self, client):
        resp = client.post("/admin/samples", data={
            "tenant_id": TENANT,
            "item_number": "ADMIN-CREATE-001",
            "name": "Admin Create Test",
        })
        assert resp.status_code == 200
        assert "ADMIN-CREATE-001" in resp.text

    def test_created_sku_appears_in_list(self, client):
        client.post("/admin/samples", data={
            "tenant_id": TENANT,
            "item_number": "ADMIN-LIST-TEST-001",
            "name": "Admin List Test SKU",
        })
        resp = client.get(f"/admin/samples?tenant_id={TENANT}")
        assert resp.status_code == 200
        assert "ADMIN-LIST-TEST-001" in resp.text

    def test_duplicate_item_number_returns_409(self, client):
        client.post("/admin/samples", data={
            "tenant_id": TENANT,
            "item_number": "ADMIN-DUP-001",
            "name": "Duplicate Test A",
        })
        resp = client.post("/admin/samples", data={
            "tenant_id": TENANT,
            "item_number": "ADMIN-DUP-001",
            "name": "Duplicate Test B",
        })
        assert resp.status_code == 409

    def test_duplicate_shows_error_message(self, client):
        client.post("/admin/samples", data={
            "tenant_id": TENANT,
            "item_number": "ADMIN-DUP-ERR-001",
            "name": "Dup Error A",
        })
        resp = client.post("/admin/samples", data={
            "tenant_id": TENANT,
            "item_number": "ADMIN-DUP-ERR-001",
            "name": "Dup Error B",
        })
        assert "already exists" in resp.text


# ─── Detail page ───────────────────────────────────────────────────────────


class TestAdminDetailPage:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.sku_id = _make_sku(client, "ADMIN-DETAIL-001", "Admin Detail Test")

    def test_detail_returns_200(self, client):
        resp = client.get(f"/admin/samples/{self.sku_id}?tenant_id={TENANT}")
        assert resp.status_code == 200

    def test_detail_shows_item_number(self, client):
        resp = client.get(f"/admin/samples/{self.sku_id}?tenant_id={TENANT}")
        assert "ADMIN-DETAIL-001" in resp.text

    def test_detail_owns_manual_usb_standard_sample_capture(self, client):
        resp = client.get(f"/admin/samples/{self.sku_id}?tenant_id={TENANT}")
        html = resp.text
        assert 'id="sample-camera-start"' in html
        assert 'id="sample-camera-capture"' in html
        assert 'id="sample-camera-upload-confirm"' in html
        assert 'id="sample-camera-retake"' in html
        assert 'value="camera" checked' in html
        assert "/static/sample_camera.js" in html
        assert translate("sample.detail.capture_usb", "en") in html

    def test_detection_points_are_authored_in_studio_conversation(self, client):
        resp = client.get(f"/admin/samples/{self.sku_id}?tenant_id={TENANT}")
        html = resp.text
        assert "/detection-points" not in html
        assert f"/admin/studio?tenant_id={TENANT}" in html
        assert translate("sample.detail.studio_detection_hint", "en") in html

class TestAdminSampleI18n:
    def test_sample_workspace_renders_and_switches_to_chinese(self, client):
        sku_id = _make_sku(client, "ADMIN-I18N-001", "Admin I18n Test")
        client.cookies.set(LANGUAGE_COOKIE, "zh-CN")
        try:
            list_body = client.get(f"/admin/samples?tenant_id={TENANT}").text
            new_body = client.get(f"/admin/samples/new?tenant_id={TENANT}").text
            detail_body = client.get(
                f"/admin/samples/{sku_id}?tenant_id={TENANT}"
            ).text

            for body in (list_body, new_body, detail_body):
                assert '<html lang="zh-CN">' in body
                assert translate("sample.admin.title", "zh-CN") in body
                assert translate("sample.nav.studio", "zh-CN") in body
                assert "Admin Studio" not in body

            assert translate("sample.list.subtitle", "zh-CN") in list_body
            assert translate("sample.new.title", "zh-CN") in new_body
            assert translate("sample.detail.standard_photos", "zh-CN") in detail_body
            assert translate("sample.detail.capture_usb", "zh-CN") in detail_body
            assert translate("sample.detail.inspection_requirements", "zh-CN") in detail_body
            assert translate("sample.detail.detection_points", "zh-CN") in detail_body
        finally:
            client.cookies.delete(LANGUAGE_COOKIE)

    def test_duplicate_error_uses_selected_language(self, client):
        _make_sku(client, "ADMIN-I18N-DUP-001", "Admin I18n Duplicate")
        client.cookies.set(LANGUAGE_COOKIE, "zh-CN")
        try:
            resp = client.post(
                "/admin/samples",
                data={
                    "tenant_id": TENANT,
                    "item_number": "ADMIN-I18N-DUP-001",
                    "name": "Duplicate",
                },
            )
            assert resp.status_code == 409
            assert "物料编号“ADMIN-I18N-DUP-001”已存在。" in resp.text
        finally:
            client.cookies.delete(LANGUAGE_COOKIE)


def test_legacy_relative_photo_path_uses_persistent_root(tmp_path, monkeypatch):
    from src.api import sample_admin_router

    root = tmp_path / "persistent-qc-samples"
    target = root / "demo" / "sku1" / "photos" / "sample.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"sample")
    monkeypatch.setattr(sample_admin_router, "_DATA_DIR", root)

    resolved = sample_admin_router.resolve_sample_photo_path(
        "data/qc_samples/demo/sku1/photos/sample.jpg"
    )
    assert resolved == target.resolve()
    assert sample_admin_router.resolve_sample_photo_path("/etc/passwd") is None


# ─── Photo upload / registration ────────────────────────────────────────────────


class TestAdminPhotoRegistration:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.sku_id = _make_sku(client, "ADMIN-PHOTO-URL-001", "Admin Photo URL Test")

    def test_register_url_photo_shows_in_detail(self, client):
        resp = client.post(f"/admin/samples/{self.sku_id}/photos", data={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/test-admin.jpg",
            "angle": "front",
            "view_type": "standard",
            "is_primary": "true",
        })
        assert resp.status_code == 200
        assert "test-admin.jpg" in resp.text

    def test_upload_png_file(self, client):
        # Minimal valid 1x1 red PNG
        png_1x1 = bytes([
            0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
            0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xde, 0x00, 0x00, 0x00, 0x0c, 0x49, 0x44, 0x41,
            0x54, 0x78, 0x9c, 0x62, 0xf8, 0x0f, 0x00, 0x00,
            0x01, 0x01, 0x00, 0x05, 0x18, 0xd8, 0x4e, 0x00,
            0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae,
            0x42, 0x60, 0x82,
        ])
        resp = client.post(
            f"/admin/samples/{self.sku_id}/photos",
            data={"tenant_id": TENANT, "angle": "back"},
            files={"photo_file": ("test_upload.png", io.BytesIO(png_1x1), "image/png")},
        )
        assert resp.status_code == 200

    def test_uploaded_photo_is_rendered_and_served(self, client):
        png = _tiny_png()
        resp = client.post(
            f"/admin/samples/{self.sku_id}/photos",
            data={"tenant_id": TENANT, "is_primary": "true"},
            files={"photo_file": ("visible.png", io.BytesIO(png), "image/png")},
        )
        assert resp.status_code == 200
        match = re.search(r'src="(/admin/samples/photos/[^"]+)"', resp.text)
        assert match is not None
        assert "data/qc_samples" not in resp.text
        served = client.get(match.group(1).replace("&amp;", "&"))
        assert served.status_code == 200
        assert served.headers["content-type"] == "image/png"
        assert served.content == png

# ─── Set primary ──────────────────────────────────────────────────────────────


class TestAdminSetPrimary:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.sku_id = _make_sku(client, "ADMIN-PRIMARY-001", "Admin Set Primary Test")
        client.post(f"/admin/samples/{self.sku_id}/photos", data={
            "tenant_id": TENANT,
            "image_url": "http://example.com/photo-a.jpg",
            "is_primary": "true",
        })
        client.post(f"/admin/samples/{self.sku_id}/photos", data={
            "tenant_id": TENANT,
            "image_url": "http://example.com/photo-b.jpg",
        })
        api_detail = client.get(f"/api/v1/sku/{self.sku_id}", params={"tenant_id": TENANT})
        self.photos = api_detail.json().get("photos", [])

    def test_set_primary_clears_previous(self, client):
        if len(self.photos) < 2:
            pytest.skip("Need at least 2 photos")
        photo_b_id = self.photos[1]["id"]
        resp = client.post(
            f"/admin/samples/{self.sku_id}/photos/{photo_b_id}/set-primary",
            data={"tenant_id": TENANT},
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/v1/sku/{self.sku_id}", params={"tenant_id": TENANT})
        assert detail.json()["reference_image_url"] == "http://example.com/photo-b.jpg"


# ─── Requirements ────────────────────────────────────────────────────────────


class TestAdminRequirements:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.sku_id = _make_sku(client, "ADMIN-REQ-001", "Admin Req Test")

    def test_add_requirement_shows_in_detail(self, client):
        resp = client.post(f"/admin/samples/{self.sku_id}/requirements", data={
            "tenant_id": TENANT,
            "code": "REQ-ADMIN-001",
            "title": "No visible stain",
            "requirement_text": "No visible stain on visible surface",
            "severity": "major",
        })
        assert resp.status_code == 200
        assert "REQ-ADMIN-001" in resp.text


# ─── Detection points ──────────────────────────────────────────────────────────


class TestAdminDetectionPoints:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.sku_id = _make_sku(client, "ADMIN-DP-001", "Admin DP Test")

    def test_add_detection_point_with_roi(self, client):
        resp = client.post(f"/admin/samples/{self.sku_id}/detection-points", data={
            "tenant_id": TENANT,
            "point_code": "DP-ADMIN-001",
            "label": "Front check",
            "roi_json_text": '{"x":0.1,"y":0.2,"w":0.3,"h":0.25}',
            "severity": "major",
        })
        assert resp.status_code == 200
        assert "DP-ADMIN-001" in resp.text

    def test_add_detection_point_invalid_roi_returns_400(self, client):
        resp = client.post(f"/admin/samples/{self.sku_id}/detection-points", data={
            "tenant_id": TENANT,
            "point_code": "DP-ADMIN-BAD",
            "label": "Bad ROI",
            "roi_json_text": "not-valid-json{{{",
            "severity": "major",
        })
        assert resp.status_code == 400


# ─── Archive ──────────────────────────────────────────────────────────────────


class TestAdminArchive:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.sku_id = _make_sku(client, "ADMIN-ARCHIVE-001", "Admin Archive Test")

    def test_archive_hides_from_sku_search(self, client):
        resp = client.post(f"/admin/samples/{self.sku_id}/archive", data={"tenant_id": TENANT})
        assert resp.status_code == 200
        search = client.get("/api/v1/sku/search", params={"q": "ADMIN-ARCHIVE-001", "tenant_id": TENANT})
        assert all(i["item_number"] != "ADMIN-ARCHIVE-001" for i in search.json()["items"])

    def test_archive_hides_from_admin_list(self, client):
        sku_id2 = _make_sku(client, "ADMIN-ARCHIVE-002", "Admin Archive Test 2")
        client.post(f"/admin/samples/{sku_id2}/archive", data={"tenant_id": TENANT})
        resp = client.get(f"/admin/samples?tenant_id={TENANT}")
        assert "ADMIN-ARCHIVE-002" not in resp.text
