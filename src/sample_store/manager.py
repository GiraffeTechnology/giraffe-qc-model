"""Sample library management — import standard photos, query by SKU."""
from __future__ import annotations
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from src.config import sample_store_dir
from src.db.models import SampleItem


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_sku(sku_id: str) -> str:
    """Strip characters that could cause path traversal or invalid filenames."""
    return re.sub(r"[^\w\-]", "_", sku_id)[:64]


def import_sample(
    db: Session,
    sku_id: str,
    image_source: str,
    product_name: str | None = None,
    notes: str | None = None,
) -> SampleItem:
    """
    Copy image_source into the sample store and create a DB record.

    Each import gets a unique destination filename so repeated imports of
    the same source file never overwrite earlier versions.
    Returns the new SampleItem.
    """
    store = sample_store_dir()
    store.mkdir(parents=True, exist_ok=True)

    src      = Path(image_source)
    safe_sku = _safe_sku(sku_id)
    ts_ms    = int(time.time() * 1000)
    uid      = uuid4().hex[:8]
    dest     = store / f"{safe_sku}_{ts_ms}_{uid}_{src.name}"
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
