"""Provision an isolated CTYUN MySQL schema and a least-privilege sandbox user.

The root password is accepted only through ``MYSQL_ROOT_PASSWORD``. It and the
generated application password are never logged. The output is a local runtime
env file with mode 0600 and must remain untracked.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote_plus

import pymysql


IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def _identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe {label}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--database", default="giraffe_qc_sandbox")
    parser.add_argument("--app-user", default="giraffe_qc_app")
    parser.add_argument("--client-host", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-env", required=True)
    args = parser.parse_args(argv)
    database = _identifier(args.database, "database")
    app_user = _identifier(args.app_user, "application user")
    root_password = os.getenv("MYSQL_ROOT_PASSWORD", "")
    if not root_password:
        raise RuntimeError("MYSQL_ROOT_PASSWORD is required")
    app_password = secrets.token_urlsafe(32)

    connection = pymysql.connect(
        host=args.host,
        port=args.port,
        user="root",
        password=root_password,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=10,
    )
    try:
        account = f"{connection.escape(app_user)}@{connection.escape(args.client_host)}"
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
            cursor.execute(f"CREATE USER IF NOT EXISTS {account} IDENTIFIED BY %s", (app_password,))
            cursor.execute(f"ALTER USER {account} IDENTIFIED BY %s", (app_password,))
            cursor.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, "
                f"REFERENCES ON `{database}`.* TO {account}"
            )
    finally:
        connection.close()

    data_root = Path(args.data_root).expanduser().resolve()
    sample_root = data_root / "samples"
    capture_root = data_root / "captures"
    for directory in (data_root, sample_root, capture_root):
        directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    db_url = (
        f"mysql+pymysql://{quote_plus(app_user)}:{quote_plus(app_password)}@"
        f"{args.host}:{args.port}/{database}?charset=utf8mb4"
    )
    output = Path(args.output_env)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"QC_DB_URL={db_url}\n")
        handle.write(f"SAMPLE_STORE_DIR={sample_root}\n")
        handle.write(f"CAPTURE_DIR={capture_root}\n")
        handle.write(f"STAGE1_DATA_ROOT={data_root}\n")
    output.chmod(0o600)
    os.environ["QC_DB_URL"] = db_url
    from src.db.session import init_db, reset_db_state

    reset_db_state()
    init_db()
    print(
        "provisioned isolated MySQL schema, initialized QC tables, and wrote "
        "restricted runtime env; secrets redacted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
