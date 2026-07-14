"""Tests for the SKU catalog API — Android-compatible SKU search and detail endpoints."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_models  # noqa: F401 — registers qc_* tables with Base
import src.db.sku_models  # noqa: F401 — registers qc_sku_* tables with Base
from src.api.main import app
from src.api.deps import get_db_dep


# ─── Fixtures ───────────────────────────────────────────────────────────────────────────────


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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


TENANT = "default"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ─── Unit: SKU Model Creation ────────────────────────────────────────────────────────────────────────


class TestSkuModelCreation:
    def test_create_sku_success(self, client):
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-MODEL-001",
            "name": "Test SKU Model",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["item_number"] == "ITEM-MODEL-001"
        assert data["name"] == "Test SKU Model"
        assert data["status"] == "active"
        assert "id" in data

    def test_create_sku_with_category(self, client):
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-MODEL-002",
            "name": "Categorized SKU",
            "category": "electronics",
        })
        assert resp.status_code == 201
        assert resp.json()["category"] == "electronics"

    def test_create_sku_with_description(self, client):
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-MODEL-003",
            "name": "Described SKU",
            "description": "A test SKU with description",
        })
        assert resp.status_code == 201
        assert resp.json()["description"] == "A test SKU with description"

    def test_create_sku_default_tenant(self, client):
        resp = client.post("/api/v1/sku", json={
            "item_number": "ITEM-MODEL-004",
            "name": "Default Tenant SKU",
        })
        assert resp.status_code == 201
        assert resp.json()["tenant_id"] == "default"

    def test_create_duplicate_item_number_returns_409(self, client):
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-DUP-UNIQUE-001",
            "name": "Duplicate Test A",
        })
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-DUP-UNIQUE-001",
            "name": "Duplicate Test B",
        })
        assert resp.status_code == 409

    def test_same_item_number_different_tenant_is_allowed(self, client):
        client.post("/api/v1/sku", json={
            "tenant_id": "tenant-a",
            "item_number": "ITEM-CROSS-TENANT-001",
            "name": "Cross Tenant A",
        })
        resp = client.post("/api/v1/sku", json={
            "tenant_id": "tenant-b",
            "item_number": "ITEM-CROSS-TENANT-001",
            "name": "Cross Tenant B",
        })
        assert resp.status_code == 201


# ─── Unit: Photo Metadata Creation ────────────────────────────────────────────────────────────────────


class TestPhotoMetadataCreation:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ITEM-PHOTO-{_uid()}",
            "name": "Photo Test SKU",
        })
        self.sku_id = resp.json()["id"]

    def test_add_photo_success(self, client):
        resp = client.post(f"/api/v1/sku/{self.sku_id}/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/test.jpg",
            "local_path": "/factory/ref/test.jpg",
            "angle": "front",
            "view_type": "standard",
            "is_primary": True,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["sku_id"] == self.sku_id
        assert data["is_primary"] is True

    def test_add_photo_returns_id(self, client):
        resp = client.post(f"/api/v1/sku/{self.sku_id}/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/test-back.jpg",
        })
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_add_photo_unknown_sku_returns_404(self, client):
        resp = client.post("/api/v1/sku/NONEXISTENT/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://example.com/photo.jpg",
        })
        assert resp.status_code == 404


# ─── Unit: Primary Photo Selection ───────────────────────────────────────────────────────────────────


class TestPrimaryPhotoSelection:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.item_number = f"ITEM-PRIMARY-{_uid()}"
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": self.item_number,
            "name": "Primary Photo Test SKU",
        })
        self.sku_id = resp.json()["id"]

    def test_primary_photo_appears_in_search(self, client):
        client.post(f"/api/v1/sku/{self.sku_id}/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/primary.jpg",
            "local_path": "/factory/ref/primary.jpg",
            "is_primary": True,
        })
        resp = client.get("/api/v1/sku/search", params={"q": self.item_number, "tenant_id": TENANT})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["reference_image_url"] == "http://192.168.1.10:8080/assets/ref/primary.jpg"
        assert items[0]["standard_photo_path"] == "/factory/ref/primary.jpg"

    def test_second_primary_clears_first(self, client):
        client.post(f"/api/v1/sku/{self.sku_id}/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/first.jpg",
            "is_primary": True,
        })
        client.post(f"/api/v1/sku/{self.sku_id}/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/second.jpg",
            "is_primary": True,
        })
        detail = client.get(f"/api/v1/sku/{self.sku_id}", params={"tenant_id": TENANT})
        assert detail.status_code == 200
        assert detail.json()["reference_image_url"] == "http://192.168.1.10:8080/assets/ref/second.jpg"


# ─── Unit: Inspection Requirement Creation ───────────────────────────────────────────────────────────────────


class TestInspectionRequirementCreation:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ITEM-REQ-{_uid()}",
            "name": "Requirement Test SKU",
        })
        self.sku_id = resp.json()["id"]

    def test_add_requirement_success(self, client):
        resp = client.post(f"/api/v1/sku/{self.sku_id}/requirements", json={
            "tenant_id": TENANT,
            "code": "REQ-001",
            "title": "No visible stain",
            "requirement_text": "No visible stain on visible surface",
            "severity": "major",
            "pass_criteria": "No stain larger than 2mm",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "REQ-001"
        assert data["sku_id"] == self.sku_id

    def test_add_requirement_with_sort_order(self, client):
        resp = client.post(f"/api/v1/sku/{self.sku_id}/requirements", json={
            "tenant_id": TENANT,
            "code": "REQ-002",
            "title": "Color check",
            "requirement_text": "Color must match reference",
            "sort_order": 5,
        })
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_add_requirement_unknown_sku_returns_404(self, client):
        resp = client.post("/api/v1/sku/NONEXISTENT/requirements", json={
            "tenant_id": TENANT,
            "code": "REQ-X",
            "title": "Test",
            "requirement_text": "Test requirement",
        })
        assert resp.status_code == 404


# ─── Unit: Detection Point Creation ───────────────────────────────────────────────────────────────────────────


class TestDetectionPointCreation:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ITEM-DP-{_uid()}",
            "name": "Detection Point Test SKU",
        })
        self.sku_id = resp.json()["id"]

    def test_add_detection_point_success(self, client):
        resp = client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "point_code": "DP-FRONT-001",
            "label": "Front surface stain check",
            "description": "Check visible front surface for stain",
            "roi_json": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
            "severity": "major",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["point_code"] == "DP-FRONT-001"
        assert data["sku_id"] == self.sku_id

    def test_add_detection_point_with_requirement_link(self, client):
        req_resp = client.post(f"/api/v1/sku/{self.sku_id}/requirements", json={
            "tenant_id": TENANT,
            "code": "REQ-DP-LINK",
            "title": "Linked req",
            "requirement_text": "Test",
        })
        req_id = req_resp.json()["id"]

        dp_resp = client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "requirement_id": req_id,
            "point_code": "DP-LINKED-001",
            "label": "Linked detection point",
        })
        assert dp_resp.status_code == 201

    def test_add_detection_point_unknown_sku_returns_404(self, client):
        resp = client.post("/api/v1/sku/NONEXISTENT/detection-points", json={
            "tenant_id": TENANT,
            "point_code": "DP-X",
            "label": "Test",
        })
        assert resp.status_code == 404

    def test_edit_detection_point_persists_fields_and_preserves_identity(self, client):
        created = client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "point_code": "DP-EDIT-001",
            "label": "Before",
        }).json()
        resp = client.patch(f"/admin/studio/detection-points/{created['id']}", json={
            "tenant_id": TENANT,
            "point_code": "DP-EDIT-001",
            "label": "After",
            "method_hint": "counting",
            "expected_value": "12",
            "severity": "critical",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == created["id"]
        assert resp.json()["label"] == "After"
        assert resp.json()["expected_value"] == "12"

    def test_edit_counting_point_without_expected_value_fails_closed(self, client):
        created = client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "point_code": "DP-EDIT-002",
            "label": "Before",
        }).json()
        resp = client.patch(f"/admin/studio/detection-points/{created['id']}", json={
            "tenant_id": TENANT,
            "point_code": "DP-EDIT-002",
            "label": "After",
            "method_hint": "counting",
            "severity": "major",
        })
        assert resp.status_code == 400


# ─── P2: Detection Point requirement_id Validation ────────────────────────────────────────────


class TestDetectionPointRequirementValidation:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        u = _uid()
        # Main SKU and its requirement
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ITEM-REQ-MAIN-{u}",
            "name": "Req Validation Main SKU",
        })
        self.sku_id = resp.json()["id"]
        req_resp = client.post(f"/api/v1/sku/{self.sku_id}/requirements", json={
            "tenant_id": TENANT,
            "code": f"REQ-MAIN-{u}",
            "title": "Main Requirement",
            "requirement_text": "Test",
        })
        self.req_id = req_resp.json()["id"]

        # Different SKU and its requirement (same tenant)
        resp2 = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ITEM-REQ-OTHER-{u}",
            "name": "Req Validation Other SKU",
        })
        self.other_sku_id = resp2.json()["id"]
        req_resp2 = client.post(f"/api/v1/sku/{self.other_sku_id}/requirements", json={
            "tenant_id": TENANT,
            "code": f"REQ-OTHER-{u}",
            "title": "Other Requirement",
            "requirement_text": "Test",
        })
        self.other_req_id = req_resp2.json()["id"]

        # Cross-tenant SKU and requirement
        other_tenant = f"tenant-x-{u}"
        resp3 = client.post("/api/v1/sku", json={
            "tenant_id": other_tenant,
            "item_number": f"ITEM-REQ-X-{u}",
            "name": "Cross Tenant SKU",
        })
        self.cross_sku_id = resp3.json()["id"]
        req_resp3 = client.post(f"/api/v1/sku/{self.cross_sku_id}/requirements", json={
            "tenant_id": other_tenant,
            "code": f"REQ-X-{u}",
            "title": "Cross Tenant Requirement",
            "requirement_text": "Test",
        })
        self.cross_req_id = req_resp3.json()["id"]

    def test_same_sku_requirement_accepted(self, client):
        resp = client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "requirement_id": self.req_id,
            "point_code": f"DP-VALID-{_uid()}",
            "label": "Valid DP",
        })
        assert resp.status_code == 201

    def test_different_sku_requirement_rejected(self, client):
        # other_req_id belongs to other_sku, not sku_id
        resp = client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "requirement_id": self.other_req_id,
            "point_code": f"DP-WRONG-SKU-{_uid()}",
            "label": "Wrong SKU DP",
        })
        assert resp.status_code == 400

    def test_nonexistent_requirement_rejected(self, client):
        resp = client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "requirement_id": "nonexistent-req-id-99999",
            "point_code": f"DP-NOEXIST-{_uid()}",
            "label": "Nonexistent Req DP",
        })
        assert resp.status_code == 400

    def test_cross_tenant_requirement_rejected(self, client):
        # cross_req_id belongs to a different tenant
        resp = client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "requirement_id": self.cross_req_id,
            "point_code": f"DP-CROSS-{_uid()}",
            "label": "Cross Tenant DP",
        })
        assert resp.status_code == 400


# ─── P2: LIKE Wildcard Escaping ─────────────────────────────────────────────────────────────────────


class TestSearchLikeEscaping:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.u = _uid()
        # Items for underscore escaping tests:
        #   exact_under has literal _ between ABC and DEF
        #   near_under  has X instead of _ (would match if _ were a wildcard)
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ESCAPE-UNDER-{self.u}",
            "name": f"ABC_DEF_{self.u}",
        })
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ESCAPE-NEARUNDER-{self.u}",
            "name": f"ABCXDEF_{self.u}",
        })
        # Items for percent escaping tests:
        #   exact_pct  has literal % between GHI and JKL
        #   near_pct   has long text instead (would match if % were a wildcard)
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ESCAPE-PCT-{self.u}",
            "name": f"GHI%JKL_{self.u}",
        })
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": f"ESCAPE-NEARPCT-{self.u}",
            "name": f"GHIanythingJKL_{self.u}",
        })

    def test_normal_search_still_works(self, client):
        resp = client.get("/api/v1/sku/search", params={"q": self.u, "tenant_id": TENANT})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 4

    def test_underscore_not_treated_as_wildcard(self, client):
        resp = client.get("/api/v1/sku/search", params={
            "q": f"ABC_DEF_{self.u}",
            "tenant_id": TENANT,
        })
        assert resp.status_code == 200
        names = [i["name"] for i in resp.json()["items"]]
        assert f"ABC_DEF_{self.u}" in names
        assert f"ABCXDEF_{self.u}" not in names

    def test_percent_not_treated_as_wildcard(self, client):
        resp = client.get("/api/v1/sku/search", params={
            "q": f"GHI%JKL_{self.u}",
            "tenant_id": TENANT,
        })
        assert resp.status_code == 200
        names = [i["name"] for i in resp.json()["items"]]
        assert f"GHI%JKL_{self.u}" in names
        assert f"GHIanythingJKL_{self.u}" not in names

    def test_literal_underscore_search_returns_underscore_items(self, client):
        resp = client.get("/api/v1/sku/search", params={
            "q": f"ESCAPE-UNDER-{self.u}",
            "tenant_id": TENANT,
        })
        items = resp.json()["items"]
        assert any(i["item_number"] == f"ESCAPE-UNDER-{self.u}" for i in items)
        assert all(i["item_number"] != f"ESCAPE-NEARUNDER-{self.u}" for i in items)


# ─── API: Search ─────────────────────────────────────────────────────────────────────────────────


class TestSkuSearch:
    def test_empty_query_returns_empty_list(self, client):
        resp = client.get("/api/v1/sku/search", params={"q": "", "tenant_id": TENANT})
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    def test_whitespace_query_returns_empty_list(self, client):
        resp = client.get("/api/v1/sku/search", params={"q": "   ", "tenant_id": TENANT})
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    def test_search_by_item_number(self, client):
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-SEARCH-UNIQUE-777",
            "name": "Search Test SKU",
        })
        resp = client.get("/api/v1/sku/search", params={"q": "SEARCH-UNIQUE-777", "tenant_id": TENANT})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        assert any(i["item_number"] == "ITEM-SEARCH-UNIQUE-777" for i in items)

    def test_search_by_name(self, client):
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-BYNAME-001",
            "name": "UniqueNameForSearchTest999",
        })
        resp = client.get("/api/v1/sku/search", params={"q": "UniqueNameForSearchTest999", "tenant_id": TENANT})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        assert any(i["name"] == "UniqueNameForSearchTest999" for i in items)

    def test_search_case_insensitive(self, client):
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-CASE-001",
            "name": "CaseSensitivityTest",
        })
        resp = client.get("/api/v1/sku/search", params={"q": "casesensitivitytest", "tenant_id": TENANT})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    def test_search_response_has_required_android_fields(self, client):
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-ANDROID-FIELDS-001",
            "name": "Android Fields Test",
        })
        resp = client.get("/api/v1/sku/search", params={"q": "ITEM-ANDROID-FIELDS-001", "tenant_id": TENANT})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        item = items[0]
        assert "id" in item
        assert "item_number" in item
        assert "name" in item
        assert "reference_image_url" in item
        assert "standard_photo_path" in item

    def test_no_crash_on_missing_photo(self, client):
        client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-NOPHOTO-001",
            "name": "No Photo SKU Test",
        })
        resp = client.get("/api/v1/sku/search", params={"q": "ITEM-NOPHOTO-001", "tenant_id": TENANT})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        item = items[0]
        assert item["reference_image_url"] is None
        assert item["standard_photo_path"] is None

    def test_search_default_tenant_id(self, client):
        client.post("/api/v1/sku", json={
            "item_number": "ITEM-DEFAULTTENANT-001",
            "name": "Default Tenant Search Test",
        })
        resp = client.get("/api/v1/sku/search", params={"q": "ITEM-DEFAULTTENANT-001"})
        assert resp.status_code == 200
        assert "items" in resp.json()


# ─── API: Detail ─────────────────────────────────────────────────────────────────────────────────


class TestSkuDetail:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.item_number = f"ITEM-DETAIL-{_uid()}"
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": self.item_number,
            "name": "Detail Test SKU",
            "category": "test_category",
            "description": "A test SKU for detail tests",
        })
        self.sku_id = resp.json()["id"]

    def test_get_sku_success(self, client):
        resp = client.get(f"/api/v1/sku/{self.sku_id}", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == self.sku_id
        assert data["item_number"] == self.item_number
        assert data["category"] == "test_category"

    def test_get_sku_includes_photos(self, client):
        client.post(f"/api/v1/sku/{self.sku_id}/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/detail.jpg",
            "local_path": "/factory/ref/detail.jpg",
            "angle": "front",
            "view_type": "standard",
            "is_primary": True,
        })
        resp = client.get(f"/api/v1/sku/{self.sku_id}", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["photos"]) >= 1
        assert data["reference_image_url"] == "http://192.168.1.10:8080/assets/ref/detail.jpg"

    def test_get_sku_includes_requirements(self, client):
        client.post(f"/api/v1/sku/{self.sku_id}/requirements", json={
            "tenant_id": TENANT,
            "code": "REQ-DETAIL-001",
            "title": "No stain",
            "requirement_text": "No stain on surface",
            "severity": "major",
        })
        resp = client.get(f"/api/v1/sku/{self.sku_id}", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        reqs = resp.json()["inspection_requirements"]
        assert len(reqs) >= 1
        assert any(r["code"] == "REQ-DETAIL-001" for r in reqs)

    def test_get_sku_includes_detection_points(self, client):
        client.post(f"/api/v1/sku/{self.sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "point_code": "DP-DETAIL-001",
            "label": "Detail check",
            "roi_json": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
            "severity": "major",
        })
        resp = client.get(f"/api/v1/sku/{self.sku_id}", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        dps = resp.json()["detection_points"]
        assert len(dps) >= 1
        assert any(dp["point_code"] == "DP-DETAIL-001" for dp in dps)

    def test_get_sku_not_found_returns_404(self, client):
        resp = client.get("/api/v1/sku/NONEXISTENT_SKU_ID_12345", params={"tenant_id": TENANT})
        assert resp.status_code == 404

    def test_get_sku_default_tenant_id(self, client):
        resp = client.get(f"/api/v1/sku/{self.sku_id}")
        assert resp.status_code == 200


# ─── Android Contract Test ──────────────────────────────────────────────────────────────────────────────


class TestAndroidContract:
    """Verify the exact JSON shape consumed by Android ApiSkuRepository."""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.item_number = f"ITEM-CONTRACT-{_uid()}"
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": self.item_number,
            "name": "Android Contract SKU",
        })
        self.sku_id = resp.json()["id"]
        client.post(f"/api/v1/sku/{self.sku_id}/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/contract.jpg",
            "local_path": "/factory/ref/contract.jpg",
            "is_primary": True,
        })

    def test_search_response_shape(self, client):
        resp = client.get("/api/v1/sku/search", params={"q": self.item_number, "tenant_id": TENANT})
        assert resp.status_code == 200
        body = resp.json()

        assert "items" in body
        assert isinstance(body["items"], list)
        assert len(body["items"]) >= 1

        item = next(i for i in body["items"] if i["item_number"] == self.item_number)
        assert item["id"] == self.sku_id
        assert item["item_number"] == self.item_number
        assert item["name"] == "Android Contract SKU"
        assert item["reference_image_url"] == "http://192.168.1.10:8080/assets/ref/contract.jpg"
        assert item["standard_photo_path"] == "/factory/ref/contract.jpg"

    def test_search_response_has_exactly_required_android_fields(self, client):
        resp = client.get("/api/v1/sku/search", params={"q": self.item_number, "tenant_id": TENANT})
        item = next(i for i in resp.json()["items"] if i["item_number"] == self.item_number)
        required_fields = {"id", "item_number", "name", "reference_image_url", "standard_photo_path"}
        assert required_fields.issubset(set(item.keys()))

    def test_search_without_tenant_id_uses_default(self, client):
        resp = client.get("/api/v1/sku/search", params={"q": self.item_number})
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_detail_response_includes_richer_fields(self, client):
        resp = client.get(f"/api/v1/sku/{self.sku_id}", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        data = resp.json()
        assert "photos" in data
        assert "inspection_requirements" in data
        assert "detection_points" in data

    def test_search_items_is_list(self, client):
        resp = client.get("/api/v1/sku/search", params={"q": self.item_number, "tenant_id": TENANT})
        assert isinstance(resp.json()["items"], list)


# ─── Inactive / Archived SKU Filtering ──────────────────────────────────────────────────────────────


class TestInactiveSkuFiltering:
    """Real test: directly mark SKU inactive/archived and confirm search excludes it."""

    def test_inactive_sku_excluded_from_search(self, client, db_session_factory):
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-INACTIVE-REAL-001",
            "name": "Inactive Real Test SKU",
        })
        assert resp.status_code == 201
        sku_id = resp.json()["id"]

        # Confirm it appears in search while active
        search = client.get("/api/v1/sku/search", params={"q": "ITEM-INACTIVE-REAL-001", "tenant_id": TENANT})
        assert any(i["item_number"] == "ITEM-INACTIVE-REAL-001" for i in search.json()["items"])

        # Directly set status to inactive via DB session
        from src.db.sku_models import QCSkuItem
        session = db_session_factory()
        try:
            sku = session.query(QCSkuItem).filter(QCSkuItem.id == sku_id).first()
            sku.status = "inactive"
            session.commit()
        finally:
            session.close()

        # Confirm it no longer appears in search
        search2 = client.get("/api/v1/sku/search", params={"q": "ITEM-INACTIVE-REAL-001", "tenant_id": TENANT})
        assert not any(i["item_number"] == "ITEM-INACTIVE-REAL-001" for i in search2.json()["items"])

    def test_archived_sku_excluded_from_search(self, client, db_session_factory):
        resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-ARCHIVED-REAL-001",
            "name": "Archived Real Test SKU",
        })
        assert resp.status_code == 201
        sku_id = resp.json()["id"]

        # Directly set status to archived
        from src.db.sku_models import QCSkuItem
        session = db_session_factory()
        try:
            sku = session.query(QCSkuItem).filter(QCSkuItem.id == sku_id).first()
            sku.status = "archived"
            session.commit()
        finally:
            session.close()

        search = client.get("/api/v1/sku/search", params={"q": "ITEM-ARCHIVED-REAL-001", "tenant_id": TENANT})
        assert not any(i["item_number"] == "ITEM-ARCHIVED-REAL-001" for i in search.json()["items"])


# ─── E2E Smoke Test ────────────────────────────────────────────────────────────────────────────────


class TestE2ESmoke:
    """Create SKU + photo + requirement + detection point, then search and validate."""

    def test_full_e2e_create_and_search(self, client):
        # Create SKU
        sku_resp = client.post("/api/v1/sku", json={
            "tenant_id": TENANT,
            "item_number": "ITEM-E2E-SMOKE-001",
            "name": "E2E Smoke Test Flower",
            "category": "artificial_flower",
            "description": "Standard inspection sample for E2E smoke test",
        })
        assert sku_resp.status_code == 201
        sku_id = sku_resp.json()["id"]

        # Add primary photo
        photo_resp = client.post(f"/api/v1/sku/{sku_id}/photos", json={
            "tenant_id": TENANT,
            "image_url": "http://192.168.1.10:8080/assets/ref/e2e-smoke.jpg",
            "local_path": "/factory/ref/e2e-smoke.jpg",
            "angle": "front",
            "view_type": "standard",
            "sha256": "abc123",
            "is_primary": True,
        })
        assert photo_resp.status_code == 201

        # Add inspection requirement
        req_resp = client.post(f"/api/v1/sku/{sku_id}/requirements", json={
            "tenant_id": TENANT,
            "code": "REQ-E2E-001",
            "title": "No visible stain",
            "requirement_text": "No visible stain on visible surface",
            "severity": "major",
            "pass_criteria": "No stain larger than 2mm",
            "sort_order": 1,
        })
        assert req_resp.status_code == 201

        # Add detection point
        dp_resp = client.post(f"/api/v1/sku/{sku_id}/detection-points", json={
            "tenant_id": TENANT,
            "point_code": "DP-E2E-001",
            "label": "Front surface stain check",
            "description": "Check visible front surface for stain",
            "roi_json": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
            "severity": "major",
            "sort_order": 1,
        })
        assert dp_resp.status_code == 201

        # Search
        search_resp = client.get("/api/v1/sku/search", params={"q": "E2E-SMOKE", "tenant_id": TENANT})
        assert search_resp.status_code == 200
        items = search_resp.json()["items"]
        assert len(items) >= 1
        found = next((i for i in items if i["item_number"] == "ITEM-E2E-SMOKE-001"), None)
        assert found is not None
        assert found["id"] == sku_id
        assert found["reference_image_url"] == "http://192.168.1.10:8080/assets/ref/e2e-smoke.jpg"
        assert found["standard_photo_path"] == "/factory/ref/e2e-smoke.jpg"

        # Detail
        detail_resp = client.get(f"/api/v1/sku/{sku_id}", params={"tenant_id": TENANT})
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == sku_id
        assert detail["item_number"] == "ITEM-E2E-SMOKE-001"
        assert detail["name"] == "E2E Smoke Test Flower"
        assert detail["category"] == "artificial_flower"
        assert detail["reference_image_url"] == "http://192.168.1.10:8080/assets/ref/e2e-smoke.jpg"
        assert detail["standard_photo_path"] == "/factory/ref/e2e-smoke.jpg"
        assert len(detail["photos"]) >= 1
        assert detail["photos"][0]["angle"] == "front"
        assert len(detail["inspection_requirements"]) >= 1
        assert detail["inspection_requirements"][0]["code"] == "REQ-E2E-001"
        assert detail["inspection_requirements"][0]["severity"] == "major"
        assert len(detail["detection_points"]) >= 1
        assert detail["detection_points"][0]["point_code"] == "DP-E2E-001"
        assert detail["detection_points"][0]["roi_json"] == {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}
