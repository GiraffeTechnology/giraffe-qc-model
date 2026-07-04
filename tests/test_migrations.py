"""Migration regression tests.

Guards two things that ``create_all``-only tables silently lost:

* ``alembic upgrade head`` actually runs to completion on a fresh database
  (catches revision-number collisions / broken chains);
* the migrated schema matches the ORM models table-for-table and
  column-for-column for the S3/S4 tables (catches drift between a model change
  and its migration).
"""
from __future__ import annotations

import pathlib

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from src.db.models import Base
# Import every model module so Base.metadata is complete for the parity check.
import src.db.sku_models          # noqa: F401
import src.db.execution_models    # noqa: F401
import src.db.intake_models       # noqa: F401
import src.db.studio_models       # noqa: F401
import src.db.qc_bundle_models    # noqa: F401
import src.db.qc_verdict_models   # noqa: F401
import src.db.pad_models          # noqa: F401

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Tables that previously existed only via create_all and now have migration 018.
_MIGRATED_TABLES = [
    "qc_bundles",
    "qc_workstations",
    "qc_bundle_assignments",
    "qc_pad_submissions",
    "qc_submitted_checkpoints",
    "qc_server_verdicts",
]


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture()
def migrated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("QC_DB_URL", url)
    command.upgrade(_alembic_config(url), "head")
    return url


def test_upgrade_head_runs_clean(migrated_db):
    insp = inspect(create_engine(migrated_db))
    tables = set(insp.get_table_names())
    for t in _MIGRATED_TABLES:
        assert t in tables, f"migration head did not create {t}"


def test_downgrade_then_upgrade_round_trips(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'rt.db'}"
    monkeypatch.setenv("QC_DB_URL", url)
    cfg = _alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "017")
    insp = inspect(create_engine(url))
    assert not (set(insp.get_table_names()) & set(_MIGRATED_TABLES)), \
        "018 downgrade must drop all S3/S4 tables"
    command.upgrade(cfg, "head")  # clean re-upgrade
    insp = inspect(create_engine(url))
    assert set(_MIGRATED_TABLES) <= set(inspect(create_engine(url)).get_table_names())


def test_migrated_schema_matches_models(migrated_db):
    """Every migrated table's columns match the ORM model's columns."""
    insp = inspect(create_engine(migrated_db))
    for table in _MIGRATED_TABLES:
        model_cols = {c.name for c in Base.metadata.tables[table].columns}
        migrated_cols = {c["name"] for c in insp.get_columns(table)}
        assert model_cols == migrated_cols, (
            f"{table}: migration/model column drift — "
            f"only in model={model_cols - migrated_cols}, "
            f"only in migration={migrated_cols - model_cols}"
        )


def test_single_head_no_revision_collision(migrated_db):
    """A revision-number collision (e.g. two 017s) yields multiple heads."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config(migrated_db))
    assert len(script.get_heads()) == 1, f"expected a single head, got {script.get_heads()}"
