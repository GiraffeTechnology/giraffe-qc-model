"""FastAPI dependencies for the QC API."""
from __future__ import annotations

from typing import Generator

from sqlalchemy.orm import Session

from src.db.session import get_db


def get_db_dep() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session.

    Delegates to the lazy session factory in src.db.session so tests
    can monkeypatch QC_DB_URL before the engine is created.
    """
    yield from get_db()
