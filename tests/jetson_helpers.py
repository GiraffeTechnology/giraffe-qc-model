"""Shared fixtures/helpers for Jetson runner (server-side) tests."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_bundle_models  # noqa: F401 — register workstation table
import src.db.qc_jetson_models  # noqa: F401 — register jetson tables
from src.db.qc_bundle_models import QCWorkstation
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
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_dep] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_workstation(db, workstation_id="WS-1", tenant_id="default", display_name="Line 1 Pad") -> QCWorkstation:
    ws = QCWorkstation(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        workstation_id=workstation_id,
        display_name=display_name,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws
