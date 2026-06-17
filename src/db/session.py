"""DB session factory — engine + session maker."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.db.models import Base

_DB_URL = os.getenv("QC_DB_URL", "sqlite:///./giraffe_qc.db")

# SQLite needs check_same_thread=False for multi-threaded FastAPI use
_connect_args = {"check_same_thread": False} if _DB_URL.startswith("sqlite") else {}

engine = create_engine(_DB_URL, connect_args=_connect_args, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Create all tables (idempotent — uses CREATE TABLE IF NOT EXISTS)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yield a session then close it."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
