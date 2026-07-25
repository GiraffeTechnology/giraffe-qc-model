"""Repo-hygiene guard for this module (PRD security requirements, §5/§9).

Scans every tracked-or-trackable file inside qc-vlm-probe/ (excluding the
gitignored samples/ and results/ directories, which hold runtime-only
customer photographs and API responses) for:

  - IPv4-looking literals -- no server IP address may ever be committed here.
  - Hardcoded DashScope/Bailian API keys (the "sk-" prefix convention).
  - A hardcoded BAILIAN_BASE_URL assignment to a literal http(s) URL, as
    opposed to a reference to an environment variable.

This is a project-specific guard on top of the repo-wide
scripts/ci/sensitive_info_lint.py denylist, which only matches a short list
of specific strings already found and removed elsewhere in the repo and
would not catch a new IP address introduced inside this module.
"""
import re
import sys
import unittest
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent

_SKIP_DIR_NAMES = {"samples", "results", "__pycache__"}

_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
_HARDCODED_BASE_URL_RE = re.compile(
    r"BAILIAN_BASE_URL\s*[:=]\s*[\"']https?://\d"
)

# 0.0.0.0 and 127.0.0.1 are generic bind/loopback addresses, not server
# identifiers, and are fine to document if ever needed.
_ALLOWED_IPS = {"0.0.0.0", "127.0.0.1"}


def _scannable_files():
    for path in MODULE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.relative_to(MODULE_ROOT).parts):
            continue
        if path.suffix in {".pyc"}:
            continue
        yield path


class TestNoLeakedInfrastructure(unittest.TestCase):
    def test_no_ip_addresses(self):
        offenders = []
        for path in _scannable_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in _IPV4_RE.finditer(text):
                if m.group(0) in _ALLOWED_IPS:
                    continue
                line_no = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(MODULE_ROOT)}:{line_no}: {m.group(0)}")
        self.assertEqual(offenders, [], "IP address literal(s) found:\n" + "\n".join(offenders))

    def test_no_hardcoded_api_keys(self):
        offenders = []
        for path in _scannable_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in _API_KEY_RE.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(MODULE_ROOT)}:{line_no}")
        self.assertEqual(offenders, [], "Hardcoded API key-shaped literal(s) found:\n" + "\n".join(offenders))

    def test_no_hardcoded_base_url(self):
        offenders = []
        for path in _scannable_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in _HARDCODED_BASE_URL_RE.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(MODULE_ROOT)}:{line_no}")
        self.assertEqual(offenders, [], "BAILIAN_BASE_URL hardcoded to a literal host:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
