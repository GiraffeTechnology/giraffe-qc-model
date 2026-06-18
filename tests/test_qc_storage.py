"""Tests for the local storage module."""
from __future__ import annotations

import hashlib
import json
import os
import pytest
from pathlib import Path

from src.storage.local_storage import (
    get_capture_dir,
    get_inspection_dir,
    get_standard_photo_dir,
    save_capture_photo,
    save_standard_photo,
)


@pytest.fixture(autouse=True)
def set_storage_root(tmp_path, monkeypatch):
    """Set QC_STORAGE_ROOT to a temp dir for all tests."""
    monkeypatch.setenv("QC_STORAGE_ROOT", str(tmp_path))


@pytest.fixture
def sample_image(tmp_path):
    """Create a minimal valid JPEG-like binary for testing."""
    img_path = tmp_path / "test_source.jpg"
    # Minimal JPEG header bytes
    img_path.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\x00" * 100
    )
    return str(img_path)


@pytest.fixture
def png_image(tmp_path):
    """Create a minimal valid PNG for testing."""
    img_path = tmp_path / "test_source.png"
    # Minimal PNG header
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return str(img_path)


class TestDirectoryPaths:
    def test_standard_photo_dir_structure(self, tmp_path):
        d = get_standard_photo_dir("tenant_a", "sku_001", "1.0")
        assert "GiraffeQC" in str(d)
        assert "standards" in str(d)
        assert "tenant_a" in str(d)
        assert "sku_001" in str(d)
        assert "1.0" in str(d)
        assert "photos" in str(d)

    def test_capture_dir_structure(self, tmp_path):
        d = get_capture_dir("tenant_a", "sku_001", "20240101")
        assert "GiraffeQC" in str(d)
        assert "captures" in str(d)
        assert "tenant_a" in str(d)
        assert "sku_001" in str(d)
        assert "20240101" in str(d)

    def test_inspection_dir_structure(self, tmp_path):
        d = get_inspection_dir("tenant_a", "sku_001", "insp_abc123")
        assert "GiraffeQC" in str(d)
        assert "inspections" in str(d)
        assert "tenant_a" in str(d)
        assert "sku_001" in str(d)
        assert "insp_abc123" in str(d)


class TestSaveStandardPhoto:
    def test_standard_photo_saved_with_correct_unique_path(self, sample_image):
        dest, sha256 = save_standard_photo(
            source_path=sample_image,
            standard_id="std_001",
            sku_id="SKU-001",
            tenant_id="tenant_a",
            version="1.0",
            angle="front",
        )
        assert dest.exists()
        assert "SKU-001" in dest.name
        assert "1.0" in dest.name
        assert "front" in dest.name

    def test_no_overwrite_on_duplicate(self, sample_image):
        """Two saves with the same params produce different filenames."""
        dest1, sha1 = save_standard_photo(
            source_path=sample_image,
            standard_id="std_001",
            sku_id="SKU-DUP",
            tenant_id="tenant_a",
            version="1.0",
            angle="front",
        )
        dest2, sha2 = save_standard_photo(
            source_path=sample_image,
            standard_id="std_001",
            sku_id="SKU-DUP",
            tenant_id="tenant_a",
            version="1.0",
            angle="front",
        )
        assert dest1 != dest2
        assert dest1.exists()
        assert dest2.exists()

    def test_sha256_computed_correctly(self, sample_image):
        dest, sha256 = save_standard_photo(
            source_path=sample_image,
            standard_id="std_001",
            sku_id="SKU-SHA",
            tenant_id="tenant_a",
            version="1.0",
            angle="front",
        )
        # Verify SHA256 matches actual file content
        h = hashlib.sha256()
        with open(dest, "rb") as f:
            h.update(f.read())
        assert sha256 == h.hexdigest()

    def test_missing_image_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            save_standard_photo(
                source_path="/nonexistent/path/image.jpg",
                standard_id="std_001",
                sku_id="SKU-MISSING",
                tenant_id="tenant_a",
                version="1.0",
                angle="front",
            )

    def test_png_extension_preserved(self, png_image):
        dest, _ = save_standard_photo(
            source_path=png_image,
            standard_id="std_001",
            sku_id="SKU-PNG",
            tenant_id="tenant_a",
            version="1.0",
            angle="front",
        )
        assert dest.suffix == ".png"


class TestSaveCapturePhoto:
    def test_capture_photo_saved(self, sample_image):
        dest, sha256 = save_capture_photo(
            source_path=sample_image,
            inspection_id="insp_001",
            tenant_id="tenant_a",
            sku_id="SKU-001",
        )
        assert dest.exists()
        assert dest.suffix == ".jpg"
        assert "CAP_" in dest.name
        assert "insp_001" in dest.name

    def test_sidecar_json_written(self, sample_image):
        dest, sha256 = save_capture_photo(
            source_path=sample_image,
            inspection_id="insp_002",
            tenant_id="tenant_b",
            sku_id="SKU-002",
        )
        sidecar = dest.with_suffix(".json")
        assert sidecar.exists()
        with open(sidecar) as f:
            data = json.load(f)
        assert data["inspection_id"] == "insp_002"
        assert data["tenant_id"] == "tenant_b"
        assert data["sku_id"] == "SKU-002"
        assert "sha256" in data
        assert "captured_at" in data

    def test_sidecar_sha256_matches_file(self, sample_image):
        dest, sha256 = save_capture_photo(
            source_path=sample_image,
            inspection_id="insp_003",
            tenant_id="tenant_a",
            sku_id="SKU-003",
        )
        sidecar = dest.with_suffix(".json")
        with open(sidecar) as f:
            data = json.load(f)
        assert data["sha256"] == sha256

    def test_missing_capture_image_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            save_capture_photo(
                source_path="/nonexistent/capture.jpg",
                inspection_id="insp_004",
                tenant_id="tenant_a",
                sku_id="SKU-MISSING",
            )

    def test_two_captures_have_unique_names(self, sample_image):
        dest1, _ = save_capture_photo(
            source_path=sample_image,
            inspection_id="insp_same",
            tenant_id="tenant_a",
            sku_id="SKU-UNIQUE",
        )
        dest2, _ = save_capture_photo(
            source_path=sample_image,
            inspection_id="insp_same",
            tenant_id="tenant_a",
            sku_id="SKU-UNIQUE",
        )
        assert dest1 != dest2


class TestStorageRootIsolation:
    def test_storage_root_read_at_call_time(self, tmp_path, monkeypatch):
        """QC_STORAGE_ROOT env change takes effect at call time."""
        new_root = tmp_path / "dynamic_root"
        monkeypatch.setenv("QC_STORAGE_ROOT", str(new_root))

        d = get_standard_photo_dir("t", "s", "v")
        assert str(d).startswith(str(new_root))
