"""Tests for the Stage 3 Group A asset-verification scripts (GAP-03, GAP-04):

* scripts/jetson_verify_mnn_lock.py — refuses an unapproved/placeholder/
  unpinned MNN SDK lockfile, and catches an archive sha256 mismatch.
* scripts/jetson_verify_model_manifest.py — refuses an unapproved/placeholder
  model manifest, catches file/size/digest mismatches on disk, and cross-
  checks the manifest's declared MNN SDK pairing against an approved lock.

These import the scripts as modules (they are plain stdlib scripts meant to
run standalone on the device) rather than shelling out, so failures show a
normal pytest traceback.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(module_path: str):
    path = REPO_ROOT / module_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lock_check = _load("scripts/jetson_verify_mnn_lock.py")
manifest_check = _load("scripts/jetson_verify_model_manifest.py")


# ── MNN SDK lock ──────────────────────────────────────────────────────────────


def test_committed_template_lock_is_refused():
    lock = json.loads((REPO_ROOT / "deploy/jetson/mnn-sdk.lock.json").read_text())
    problems = lock_check.verify(lock, archive_path=None)
    assert problems, "the committed template must never verify clean"
    assert any("approved" in p for p in problems)


def _good_lock(**overrides):
    lock = {
        "approved": True,
        "source_url": "https://example.invalid/mnn-sdk-2.8.0.tar.gz",
        "git_commit": "a" * 40,
        "sha256": "b" * 64,
        "build_flags": ["-DMNN_CUDA=OFF"],
        "target_arch": "aarch64",
        "jetpack_version": "5.1.6",
        "l4t_version": "35.6.4",
    }
    lock.update(overrides)
    return lock


def test_fully_approved_lock_passes():
    assert lock_check.verify(_good_lock(), archive_path=None) == []


def test_latest_git_commit_is_rejected():
    problems = lock_check.verify(_good_lock(git_commit="latest"), archive_path=None)
    assert any("git_commit" in p for p in problems)


def test_missing_required_field_is_rejected():
    lock = _good_lock()
    del lock["target_arch"]
    problems = lock_check.verify(lock, archive_path=None)
    assert any("target_arch" in p for p in problems)


def test_malformed_sha256_is_rejected():
    problems = lock_check.verify(_good_lock(sha256="not-a-digest"), archive_path=None)
    assert any("sha256" in p for p in problems)


def test_archive_digest_mismatch_is_rejected(tmp_path):
    archive = tmp_path / "sdk.tar.gz"
    archive.write_bytes(b"actual-bytes")
    lock = _good_lock(sha256="0" * 64)  # deliberately wrong
    problems = lock_check.verify(lock, archive_path=str(archive))
    assert any("mismatch" in p for p in problems)


def test_archive_digest_match_passes(tmp_path):
    archive = tmp_path / "sdk.tar.gz"
    archive.write_bytes(b"actual-bytes")
    digest = hashlib.sha256(b"actual-bytes").hexdigest()
    lock = _good_lock(sha256=digest)
    assert lock_check.verify(lock, archive_path=str(archive)) == []


# ── Model manifest ────────────────────────────────────────────────────────────


def test_committed_template_manifest_is_refused():
    manifest = json.loads(
        (REPO_ROOT / "deploy/jetson/model-manifest.example.json").read_text()
    )
    problems = manifest_check.verify(manifest, model_dir=str(REPO_ROOT), mnn_lock=None)
    assert problems
    assert any("approved" in p for p in problems)


def _write_model_file(tmp_path, name: str, content: bytes):
    path = tmp_path / name
    path.write_bytes(content)
    return {"path": name, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}


def _good_manifest(tmp_path, **overrides):
    file_entry = _write_model_file(tmp_path, "model.mnn", b"fake-model-bytes")
    manifest = {
        "approved": True,
        "model_name": "qwen3-vl-4b-instruct",
        "model_alias": "qwen3-vl-4b-mnn",
        "upstream_revision": "rev-123",
        "mnn_export_tool": "mnn_convert",
        "mnn_export_tool_version": "2.8.0",
        "quantization": "int4",
        "files": [file_entry],
        "min_memory_mb": 4096,
        "target_jetpack_version": "5.1.6",
        "target_l4t_version": "35.6.4",
        "target_mnn_sdk_commit": "a" * 40,
        "license": "apache-2.0",
        "source": "internal export",
    }
    manifest.update(overrides)
    return manifest


def test_fully_approved_manifest_matches_files_on_disk(tmp_path):
    manifest = _good_manifest(tmp_path)
    assert manifest_check.verify(manifest, model_dir=str(tmp_path), mnn_lock=None) == []


def test_missing_file_on_disk_is_rejected(tmp_path):
    manifest = _good_manifest(tmp_path)
    (tmp_path / "model.mnn").unlink()
    problems = manifest_check.verify(manifest, model_dir=str(tmp_path), mnn_lock=None)
    assert any("missing on disk" in p for p in problems)


def test_digest_mismatch_is_rejected(tmp_path):
    manifest = _good_manifest(tmp_path)
    (tmp_path / "model.mnn").write_bytes(b"tampered-bytes-different-length!!")
    problems = manifest_check.verify(manifest, model_dir=str(tmp_path), mnn_lock=None)
    assert any("mismatch" in p for p in problems)


def test_size_mismatch_is_rejected(tmp_path):
    manifest = _good_manifest(tmp_path)
    manifest["files"][0]["size_bytes"] = 999999
    problems = manifest_check.verify(manifest, model_dir=str(tmp_path), mnn_lock=None)
    assert any("size mismatch" in p for p in problems)


def test_missing_quantization_field_is_rejected(tmp_path):
    manifest = _good_manifest(tmp_path)
    del manifest["quantization"]
    problems = manifest_check.verify(manifest, model_dir=str(tmp_path), mnn_lock=None)
    assert any("quantization" in p for p in problems)


def test_mismatched_mnn_sdk_pairing_is_rejected(tmp_path):
    manifest = _good_manifest(tmp_path, target_mnn_sdk_commit="b" * 40)
    mnn_lock = {"approved": True, "git_commit": "a" * 40, "jetpack_version": "5.1.6"}
    problems = manifest_check.verify(manifest, model_dir=str(tmp_path), mnn_lock=mnn_lock)
    assert any("target_mnn_sdk_commit" in p for p in problems)


def test_matching_mnn_sdk_pairing_passes(tmp_path):
    manifest = _good_manifest(tmp_path, target_mnn_sdk_commit="a" * 40)
    mnn_lock = {"approved": True, "git_commit": "a" * 40, "jetpack_version": "5.1.6"}
    assert manifest_check.verify(manifest, model_dir=str(tmp_path), mnn_lock=mnn_lock) == []


def test_unapproved_mnn_lock_is_not_cross_checked(tmp_path):
    """An unapproved lock is itself invalid, so it should not gate the manifest check."""
    manifest = _good_manifest(tmp_path, target_mnn_sdk_commit="totally-different")
    mnn_lock = {"approved": False, "git_commit": "a" * 40}
    assert manifest_check.verify(manifest, model_dir=str(tmp_path), mnn_lock=mnn_lock) == []
