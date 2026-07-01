"""Rule-learning engine configuration gates.

Phase 2A has no real learning backend wired. To let the workflow (and the
admin UI's "Run learning (mock)" action) function in dev/test without a real
provider, the deterministic mock learning provider is used ONLY when explicitly
allowed. In production with no real backend, learning fails closed.
"""
from __future__ import annotations

import os

from src.config import app_env


def learning_mock_allowed() -> bool:
    """True when the deterministic mock learning provider may be used.

    Enabled by ``QC_LEARNING_ALLOW_MOCK=true`` or the test harness
    (``APP_ENV=test``). Never implies real visual accuracy.
    """
    if os.getenv("QC_LEARNING_ALLOW_MOCK", "false").strip().lower() in ("1", "true", "yes"):
        return True
    return app_env() == "test"
