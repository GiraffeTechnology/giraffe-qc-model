"""Alembic env — reads QC_DB_URL from environment, falls back to alembic.ini."""
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.getenv("QC_DB_URL")
if db_url:
    # ConfigParser treats percent signs as interpolation markers.  Database
    # URLs commonly contain percent-encoded credentials (for example %2F), so
    # escape them while storing the value; get_section()/get_main_option()
    # restores the original URL before SQLAlchemy sees it.
    config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.db.models import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
