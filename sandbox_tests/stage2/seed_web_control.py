"""Seed the Stage 2 Web control tenant in the configured database.

This is a SANDBOX-only bootstrap utility.  It creates no simulated verdicts:
the seeded SKUs have real active standard revisions and detection points, while
inspection evidence/results are produced only by the authenticated Web flow.
"""
from __future__ import annotations

import argparse

from src.db.seed_data import seed_all_fixtures
from src.db.session import SessionLocal, init_db
from src.pad.session_service import seed_demo_operators


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args(argv)

    init_db()
    db = SessionLocal()
    try:
        seed_demo_operators(db, tenant_id=args.tenant)
        skus = seed_all_fixtures(db, tenant_id=args.tenant)
        print(f"Stage 2 sandbox tenant ready: tenant={args.tenant} sku_count={len(skus)}")
        for sku in skus:
            print(f"  {sku.item_number} | {sku.name}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
