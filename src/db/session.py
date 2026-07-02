"""DB session factory — engine + session maker.

Fix C: engine and SessionLocal are created lazily so tests can monkeypatch
QC_DB_URL before the engine is created.
"""
import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.db.models import Base

# Lazy state container — engine is created on first use
_state: dict = {}


def _get_engine():
    """Return the engine, creating it lazily from QC_DB_URL on first call."""
    if "engine" not in _state:
        url = os.getenv("QC_DB_URL", "sqlite:///./giraffe_qc.db")
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _state["engine"] = create_engine(url, connect_args=connect_args, echo=False)
    return _state["engine"]


def _get_session_local():
    """Return the SessionLocal factory, creating it lazily on first call."""
    if "session_local" not in _state:
        _state["session_local"] = sessionmaker(
            bind=_get_engine(), autocommit=False, autoflush=False
        )
    return _state["session_local"]


def reset_db_state() -> None:
    """Reset cached engine and session for testing.

    Call this before monkeypatching QC_DB_URL in tests so the new URL
    is picked up when the engine is next created.
    """
    _state.clear()


# Module-level aliases for backward compatibility with existing code that
# imports 'engine' or 'SessionLocal' directly.
# These are lazy descriptors via a module __getattr__ mechanism.

class _LazyModule:
    """Wrapper that provides lazy module-level attributes."""

    @property
    def engine(self):
        return _get_engine()

    @property
    def SessionLocal(self):
        return _get_session_local()


# Keep backward-compat names accessible at module level via properties
# The simplest approach: expose engine and SessionLocal as module-level
# functions that look up the lazy state. However, to maintain strict
# backward compatibility with `from src.db.session import engine`, we
# keep the module-level names but make them re-evaluate via __getattr__.

def __getattr__(name: str):
    """Module-level __getattr__ for lazy evaluation of engine/SessionLocal."""
    if name == "engine":
        return _get_engine()
    if name == "SessionLocal":
        return _get_session_local()
    raise AttributeError(f"module 'src.db.session' has no attribute {name!r}")


def init_db() -> None:
    """Create all tables (idempotent — uses CREATE TABLE IF NOT EXISTS).

    Creates tables for old models, qc_models, new sku_models, and pad_models.
    """
    import src.db.qc_models  # noqa: F401 — side-effect import registers tables
    import src.db.sku_models  # noqa: F401 — side-effect import registers tables
    import src.db.qc_model_models  # noqa: F401 — side-effect import registers tables
    import src.db.qc_learning_models  # noqa: F401 — side-effect import registers tables
    import src.db.qc_source_models  # noqa: F401 — side-effect import registers tables
    import src.db.qc_authoring_models  # noqa: F401 — side-effect import registers tables
    import src.db.qc_sample_learning_models  # noqa: F401 — side-effect import registers tables
    import src.db.qc_readiness_models  # noqa: F401 — side-effect import registers tables
    import src.db.qc_production_models  # noqa: F401 — side-effect import registers tables
    import src.db.execution_models  # noqa: F401 — side-effect import registers tables
    import src.db.intake_models  # noqa: F401 — side-effect import registers tables
    import src.db.pad_models  # noqa: F401 — side-effect import registers tables
    Base.metadata.create_all(bind=_get_engine())


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a session then close it."""
    db: Session = _get_session_local()()
    try:
        yield db
    finally:
        db.close()
