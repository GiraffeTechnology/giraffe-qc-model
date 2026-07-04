#!/usr/bin/env python3
"""Seed Edge CV defaults (mock runner, Jetson profile, mock model) — §19.

Usage:
    uv run python scripts/seed_edge_cv_data.py

Optional env vars:
    QC_DB_URL   -- override database URL (default: sqlite:///./giraffe_qc.db)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
import src.db.edge_cv_models  # noqa: F401 — register tables
from src.db.edge_cv_seed import seed_edge_cv_defaults

DB_URL = os.getenv("QC_DB_URL", "sqlite:///./giraffe_qc.db")
TENANT = os.getenv("SEED_TENANT", "default")


def main() -> None:
    engine = create_engine(DB_URL)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        seed_edge_cv_defaults(db, TENANT)
        print(f"Seeded Edge CV defaults for tenant={TENANT} into {DB_URL}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
