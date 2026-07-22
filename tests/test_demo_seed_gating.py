"""The weak demo accounts (password == username) must never be auto-created in
production. Seeding is allowed only under APP_ENV=test or with an explicit
QC_SEED_DEMO_OPERATORS opt-in."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.pad_models  # noqa: F401
from src.db.pad_models import QCOperatorProfile
from src.pad.session_service import (
    _verify_password,
    demo_seed_allowed,
    seed_demo_operators,
)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _operator_count(db) -> int:
    return db.query(QCOperatorProfile).count()


def test_seed_refused_in_production(db_session, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("QC_SEED_DEMO_OPERATORS", raising=False)
    assert not demo_seed_allowed()
    seed_demo_operators(db_session, tenant_id="demo")
    assert _operator_count(db_session) == 0


def test_seed_allowed_in_test_env(db_session, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("QC_SEED_DEMO_OPERATORS", raising=False)
    assert demo_seed_allowed()
    seed_demo_operators(db_session, tenant_id="demo")
    assert _operator_count(db_session) > 0


def test_seed_allowed_with_explicit_opt_in(db_session, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("QC_SEED_DEMO_OPERATORS", "true")
    assert demo_seed_allowed()
    seed_demo_operators(db_session, tenant_id="demo")
    assert _operator_count(db_session) > 0


def test_verify_password_round_trip():
    from src.pad.session_service import _make_password_hash

    stored = _make_password_hash("correct horse battery staple")
    assert _verify_password("correct horse battery staple", stored)
    assert not _verify_password("wrong password", stored)
    assert not _verify_password("correct horse battery staple", "malformed-no-salt")
