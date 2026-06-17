"""Sample library management — import standard photos, query by SKU."""
from __future__ import annotations
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from src.db.models import SampleItem

_STORE_DIR = Path(os.getenv("SAMPLE_STORE_DIR", "data/samples"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def import_sample(
    db: Session,
    sku_id: str,
    image_source: str,
    product_name: str | None = None,
    notes: str | None = None,
) -> SampleItem:
    """
    Copy image_source into the sample store and create a DB record.
    Returns the new SampleItem.
    """
    _STORE_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(image_source)
    dest_name = f"{sku_id}_{src.name}"
    dest = _STORE_DIR / dest_name
    shutil.copy2(src, dest)

    item = SampleItem(
        sku_id=sku_id,
        product_name=product_name,
        image_path=str(dest),
        uploaded_at=_utcnow(),
        notes=notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_samples(db: Session, sku_id: str) -> list[SampleItem]:
    """Return all active samples for a SKU, newest first."""
    return (
        db.query(SampleItem)
        .filter(SampleItem.sku_id == sku_id, SampleItem.is_active.is_(True))
        .order_by(SampleItem.uploaded_at.desc())
        .all()
    )


def list_all_skus(db: Session) -> list[str]:
    rows = db.query(SampleItem.sku_id).filter(SampleItem.is_active.is_(True)).distinct().all()
    return [r[0] for r in rows]
