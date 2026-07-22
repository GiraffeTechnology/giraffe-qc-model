#!/usr/bin/env python3
"""Provision a real operator/admin account (production replacement for the
test-only demo seed, which is disabled outside APP_ENV=test).

Usage:
    uv run python scripts/create_operator.py \
        --username alice --role admin --tenant-id default \
        [--display-name "Alice"] [--language zh-CN]

The password is read from the QC_OPERATOR_PASSWORD environment variable or,
failing that, prompted for interactively (never accepted as a CLI argument so
it cannot leak via shell history or process listings).

Optional env vars:
    QC_DB_URL             -- database URL (default: sqlite:///./giraffe_qc.db)
    QC_OPERATOR_PASSWORD  -- password for the new account (min 12 chars)
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
import src.db.pad_models  # noqa: F401
from src.db.pad_models import QCOperatorProfile
from src.pad.session_service import _make_password_hash

MIN_PASSWORD_LENGTH = 12
ROLES = ("operator", "reviewer", "admin", "engineer")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", required=True, choices=ROLES)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    password = os.getenv("QC_OPERATOR_PASSWORD") or getpass.getpass(
        f"Password for {args.username}: "
    )
    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"error: password must be at least {MIN_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        return 1
    if password == args.username:
        print("error: password must not equal the username", file=sys.stderr)
        return 1

    db_url = os.getenv("QC_DB_URL", "sqlite:///./giraffe_qc.db")
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        existing = (
            session.query(QCOperatorProfile)
            .filter_by(tenant_id=args.tenant_id, username=args.username)
            .first()
        )
        if existing is not None:
            print(
                f"error: operator '{args.username}' already exists in tenant "
                f"'{args.tenant_id}'",
                file=sys.stderr,
            )
            return 1
        session.add(
            QCOperatorProfile(
                tenant_id=args.tenant_id,
                username=args.username,
                display_name=args.display_name or args.username,
                role=args.role,
                preferred_language=args.language,
                password_hash=_make_password_hash(password),
                is_active=True,
            )
        )
        session.commit()
    finally:
        session.close()

    print(f"created {args.role} '{args.username}' in tenant '{args.tenant_id}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
