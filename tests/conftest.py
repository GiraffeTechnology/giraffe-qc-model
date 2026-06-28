"""Shared pytest configuration for explicit test-harness behavior."""
from __future__ import annotations

import os


def pytest_configure() -> None:
    os.environ.setdefault("APP_ENV", "test")
