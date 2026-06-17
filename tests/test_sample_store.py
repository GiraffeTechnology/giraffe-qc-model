"""Tests for sample library management."""
import os
import shutil
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, SampleItem
from src.sample_store.manager import import_sample, get_samples, list_all_skus


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # Point sample store to tmp dir
    monkeypatch.setenv("SAMPLE_STORE_DIR", str(tmp_path / "samples"))
    yield session
    session.close()


def test_import_sample_copies_file_and_creates_row(db, tmp_path):
    # Create a dummy source image
    src = tmp_path / "source.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    item = import_sample(db, "SKU-001", str(src), product_name="Red Fabric")
    assert isinstance(item, SampleItem)
    assert item.id is not None
    assert item.sku_id == "SKU-001"
    assert item.product_name == "Red Fabric"
    assert item.is_active is True
    assert os.path.exists(item.image_path)


def test_get_samples_returns_active_only(db, tmp_path):
    src = tmp_path / "img.png"
    src.write_bytes(b"\x00" * 10)

    s1 = import_sample(db, "SKU-002", str(src))
    s2 = import_sample(db, "SKU-002", str(src))

    # Deactivate s1
    s1.is_active = False
    db.commit()

    results = get_samples(db, "SKU-002")
    assert len(results) == 1
    assert results[0].id == s2.id


def test_get_samples_returns_newest_first(db, tmp_path):
    src = tmp_path / "img2.png"
    src.write_bytes(b"\x00" * 10)
    import time

    s1 = import_sample(db, "SKU-003", str(src))
    time.sleep(0.01)
    s2 = import_sample(db, "SKU-003", str(src))

    results = get_samples(db, "SKU-003")
    assert results[0].id == s2.id   # newest first


def test_get_samples_unknown_sku_returns_empty(db):
    assert get_samples(db, "SKU-NONEXISTENT-ZZZZZ") == []


def test_list_all_skus(db, tmp_path):
    src = tmp_path / "img3.png"
    src.write_bytes(b"\x00" * 10)
    import_sample(db, "SKU-A", str(src))
    import_sample(db, "SKU-B", str(src))
    skus = list_all_skus(db)
    assert "SKU-A" in skus
    assert "SKU-B" in skus
