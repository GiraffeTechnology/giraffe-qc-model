"""Shared helpers for Phase 2A rule-learning tests (not a test module)."""
from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401 — register tables
import src.db.qc_model_models  # noqa: F401 — register tables
import src.db.qc_learning_models  # noqa: F401 — register tables
from src.db.sku_models import QCSkuItem


def uid() -> str:
    return uuid.uuid4().hex


def new_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def new_session():
    return new_session_factory()()


def seed_sku(db, sku_id: str = "sku1", tenant_id: str = "default") -> str:
    db.add(QCSkuItem(id=sku_id, tenant_id=tenant_id, item_number="FL-1", name="Flower Brooch"))
    db.commit()
    return sku_id


# The canonical multi-requirement operator input used across tests (PRD §18.2).
OPERATOR_REQUIREMENT_TEXT = (
    "Check flower center alignment. Verify chain link count. Check petal cracks."
)
