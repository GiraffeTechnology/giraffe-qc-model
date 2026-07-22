"""Tests for scripts/ci/sensitive_info_lint.py (P0 regression guard)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "scripts" / "ci" / "sensitive_info_lint.py"
    spec = importlib.util.spec_from_file_location("sensitive_info_lint", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint = _load()


def test_current_repo_tree_is_clean():
    problems, _notes = lint.scan()
    assert problems == []


def test_license_known_exception_is_downgraded_to_a_note():
    _problems, notes = lint.scan()
    assert any("LICENSE" in n for n in notes)


def test_denylist_catches_a_reintroduced_string(tmp_path, monkeypatch):
    # Uses a synthetic marker, not a real denylisted identifier, so this
    # test file itself never contains one of the literal strings the lint
    # watches for (which would otherwise trip the lint on its own test).
    marker = "SENSITIVE-INFO-LINT-TEST-MARKER"
    monkeypatch.setattr(lint, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(lint, "_SELF", tmp_path / "nonexistent-self.py")
    monkeypatch.setattr(lint, "_KNOWN_EXCEPTIONS", set())
    monkeypatch.setattr(lint, "_DENYLIST", (marker,))
    (tmp_path / "leaked.md").write_text(f"deployed to {marker} over ssh\n")

    import subprocess as _subprocess

    def fake_check_output(cmd, cwd, text):
        assert cmd == ["git", "ls-files"]
        return "leaked.md\n"

    monkeypatch.setattr(_subprocess, "check_output", fake_check_output)
    problems, _notes = lint.scan()
    assert any(marker in p for p in problems)


def test_main_exits_nonzero_on_failure(monkeypatch):
    monkeypatch.setattr(lint, "scan", lambda: (["fake:1: contains denylisted string 'x'"], []))
    assert lint.main() == 1


def test_main_exits_zero_when_clean(monkeypatch):
    monkeypatch.setattr(lint, "scan", lambda: ([], []))
    assert lint.main() == 0
