"""Shared pytest configuration for the jetson_runner test suite.

Mirrors ``tests/conftest.py``: this directory is not collected under the main
``tests/`` tree (pyproject.toml's ``testpaths`` only covers ``tests/``), so it
needs its own explicit ``APP_ENV=test`` -- otherwise ``src.config.app_env()``
defaults to ``"production"`` and every ``RunnerConfig(mock_mode=True)`` in
this suite would raise ``MockModeNotAllowedInProduction`` (see
``jetson_runner/app/config.py``), which is correct fail-closed behavior for a
real deployment but not what the mock-mode unit tests are exercising.
"""
from __future__ import annotations

import os


def pytest_configure() -> None:
    os.environ.setdefault("APP_ENV", "test")
