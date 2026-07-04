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
    command.downgrade(cfg, "018")
    insp = inspect(create_engine(url))
    assert not (set(insp.get_table_names()) & set(_MIGRATED_TABLES)), \
        "019 downgrade must drop all S3/S4 tables"
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


def test_upgrade_head_adopts_create_all_tables(tmp_path, monkeypatch):
    """A create_all deployment (tables already present at 017) upgrades cleanly.

    Simulates a server that ran with Base.metadata.create_all before 018 existed:
    the S3/S4 tables are already there at revision 017. `upgrade head` must adopt
    them, not fail with 'table already exists'.
    """
    url = f"sqlite:///{tmp_path / 'create_all.db'}"
    monkeypatch.setenv("QC_DB_URL", url)
    cfg = _alembic_config(url)
    engine = create_engine(url)

    command.upgrade(cfg, "018")
    # A create_all deployment materialised the S3/S4 tables already.
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables[t] for t in _MIGRATED_TABLES]
    )

    command.upgrade(cfg, "head")  # must not raise 'table already exists'

    insp = inspect(create_engine(url))
    assert set(_MIGRATED_TABLES) <= set(insp.get_table_names())
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext

    head = ScriptDirectory.from_config(cfg).get_current_head()
    with create_engine(url).connect() as conn:
        assert MigrationContext.configure(conn).get_current_revision() == head


def test_upgrade_head_fails_clearly_on_missing_column(tmp_path, monkeypatch):
    """An existing table missing a required column fails, naming the table+column."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'incompat.db'}"
    monkeypatch.setenv("QC_DB_URL", url)
    cfg = _alembic_config(url)

    command.upgrade(cfg, "018")
    # A diverged qc_bundles (missing required columns like manifest_json) exists.
    with create_engine(url).begin() as conn:
        conn.execute(text("CREATE TABLE qc_bundles (id VARCHAR(64) PRIMARY KEY, wrong_col TEXT)"))

    with pytest.raises(Exception) as exc:
        command.upgrade(cfg, "head")
    msg = str(exc.value)
    assert "qc_bundles" in msg and "incompatible" in msg.lower()
    assert "missing columns" in msg and "manifest_json" in msg  # names the column
    assert "Remediation" in msg
    # The bad schema must not have been stamped as 018.
    from alembic.runtime.migration import MigrationContext
    with create_engine(url).connect() as conn:
        assert MigrationContext.configure(conn).get_current_revision() == "018"


def test_upgrade_head_fails_on_missing_unique_constraint(tmp_path, monkeypatch):
    """An existing table with all columns but missing its unique constraint fails."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'noconstraint.db'}"
    monkeypatch.setenv("QC_DB_URL", url)
    cfg = _alembic_config(url)

    command.upgrade(cfg, "018")
    # qc_bundles with every column but NO uq_bundle_tenant_version / indexes.
    cols = ", ".join(
        f"{c} TEXT" for c in Base.metadata.tables["qc_bundles"].columns.keys()
    )
    with create_engine(url).begin() as conn:
        conn.execute(text(f"CREATE TABLE qc_bundles ({cols})"))

    with pytest.raises(Exception) as exc:
        command.upgrade(cfg, "head")
    msg = str(exc.value)
    assert "qc_bundles" in msg
    assert "unique constraint" in msg.lower() or "missing index" in msg.lower()


def test_upgrade_head_fails_on_wrong_column_definition(tmp_path, monkeypatch):
    """A table with the right column *names* but a nullable, non-PK `id` is rejected.

    Names alone are not enough — a plain nullable `id` (not the primary key)
    would allow duplicate/null ids, so adoption must fail on the definition.
    """
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'wrongdef.db'}"
    monkeypatch.setenv("QC_DB_URL", url)
    cfg = _alembic_config(url)

    command.upgrade(cfg, "018")
    # qc_bundles with every column, unique constraint and indexes present, but
    # `id` is a plain nullable column with no primary key.
    ddl = text(
        "CREATE TABLE qc_bundles ("
        " id VARCHAR(64),"
        " tenant_id VARCHAR(64) NOT NULL,"
        " bundle_version VARCHAR(64) NOT NULL,"
        " status VARCHAR(32) NOT NULL,"
        " sku_count INTEGER NOT NULL,"
        " standard_revision_count INTEGER NOT NULL,"
        " created_by VARCHAR(128),"
        " manifest_json JSON NOT NULL,"
        " manifest_sha256 VARCHAR(64) NOT NULL,"
        " signature VARCHAR(256) NOT NULL,"
        " signature_algo VARCHAR(32) NOT NULL,"
        " created_at DATETIME NOT NULL,"
        " CONSTRAINT uq_bundle_tenant_version UNIQUE (tenant_id, bundle_version))"
    )
    with create_engine(url).begin() as conn:
        conn.execute(ddl)
        conn.execute(text("CREATE INDEX ix_qc_bundles_tenant_id ON qc_bundles (tenant_id)"))
        conn.execute(text("CREATE INDEX ix_qc_bundles_bundle_version ON qc_bundles (bundle_version)"))

    with pytest.raises(Exception) as exc:
        command.upgrade(cfg, "head")
    msg = str(exc.value)
    assert "qc_bundles" in msg
    assert "primary key" in msg.lower()
    assert "not null" in msg.lower()  # names the nullable id problem


def test_upgrade_head_fails_on_optional_column_made_not_null(tmp_path, monkeypatch):
    """A column the model expects nullable but the DB made NOT NULL is rejected."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'notnulldrift.db'}"
    monkeypatch.setenv("QC_DB_URL", url)
    cfg = _alembic_config(url)

    command.upgrade(cfg, "018")
    # qc_workstations, fully correct except last_sync_status is NOT NULL (should
    # be nullable) — register_workstation() omits it, so an insert would fail.
    with create_engine(url).begin() as conn:
        conn.execute(text(
            "CREATE TABLE qc_workstations ("
            " id VARCHAR(64) NOT NULL, tenant_id VARCHAR(64) NOT NULL,"
            " workstation_id VARCHAR(128) NOT NULL, display_name VARCHAR(256) NOT NULL,"
            " site_or_line VARCHAR(256), paired_status VARCHAR(32) NOT NULL,"
            " assigned_bundle_version VARCHAR(64), installed_bundle_version VARCHAR(64),"
            " last_seen_at DATETIME, last_sync_status VARCHAR(64) NOT NULL,"
            " last_error TEXT, pairing_token VARCHAR(128), outbox_upload_status VARCHAR(64),"
            " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,"
            " PRIMARY KEY (id),"
            " CONSTRAINT uq_workstation_tenant_id UNIQUE (tenant_id, workstation_id))"
        ))
        conn.execute(text("CREATE INDEX ix_qc_workstations_tenant_id ON qc_workstations (tenant_id)"))
        conn.execute(text("CREATE INDEX ix_qc_workstations_workstation_id ON qc_workstations (workstation_id)"))

    with pytest.raises(Exception) as exc:
        command.upgrade(cfg, "head")
    msg = str(exc.value)
    assert "last_sync_status" in msg and "must be nullable" in msg.lower()


def test_upgrade_head_fails_on_foreign_key_to_wrong_column(tmp_path, monkeypatch):
    """An FK to the right parent table but the wrong parent column is rejected."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'fkdrift.db'}"
    monkeypatch.setenv("QC_DB_URL", url)
    cfg = _alembic_config(url)
    engine = create_engine(url)

    command.upgrade(cfg, "018")
    # Correct parent tables via create_all; then a child whose workstation_pk FK
    # points at qc_workstations.workstation_id instead of the primary key id.
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables[t] for t in ("qc_bundles", "qc_workstations")]
    )
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE qc_bundle_assignments ("
            " id VARCHAR(64) NOT NULL, tenant_id VARCHAR(64) NOT NULL,"
            " workstation_pk VARCHAR(64) NOT NULL, bundle_pk VARCHAR(64) NOT NULL,"
            " bundle_version VARCHAR(64) NOT NULL, assigned_by VARCHAR(128),"
            " created_at DATETIME NOT NULL, PRIMARY KEY (id),"
            " FOREIGN KEY (workstation_pk) REFERENCES qc_workstations (workstation_id),"
            " FOREIGN KEY (bundle_pk) REFERENCES qc_bundles (id))"
        ))
        for col in ("tenant_id", "workstation_pk", "bundle_pk"):
            conn.execute(text(
                f"CREATE INDEX ix_qc_bundle_assignments_{col} ON qc_bundle_assignments ({col})"))

    with pytest.raises(Exception) as exc:
        command.upgrade(cfg, "head")
    msg = str(exc.value)
    assert "qc_bundle_assignments" in msg and "foreign key" in msg.lower()
    assert "qc_workstations" in msg  # names the parent whose column is wrong
