"""Shared fixtures/helpers for Edge CV tests (in-memory DB + TestClient)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.edge_cv_models  # noqa: F401 — register tables
from src.db.edge_cv_seed import seed_edge_cv_defaults
from src.api.deps import get_db_dep
from src.api.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def seeded_db(db_session):
    seed_edge_cv_defaults(db_session, "default")
    return db_session


@pytest.fixture()
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_dep] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


def register_device(client, name="jetson-lab-1", device_type="jetson_nano_2gb", caps=None, max_jobs=1):
    caps = caps or ["opencv", "image_preprocess", "defect_candidate_detection"]
    resp = client.post(
        "/api/edge-cv/devices/register",
        json={
            "device_name": name,
            "device_type": device_type,
            "capabilities": caps,
            "max_concurrent_jobs": max_jobs,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_job(client, task_type="defect_candidate_detection", image="storage://input/x.jpg", **kw):
    body = {"task_type": task_type, "input_payload": {"image_uri": image}}
    body.update(kw)
    resp = client.post("/api/cv/jobs", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()
