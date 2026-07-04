"""Path-safety guard for user-controlled identifiers used in storage paths.

Byte-level upload validation (streamed size bound + magic-byte MIME sniff) lives
in :mod:`src.storage.upload_validation` and is the single validator every upload
route uses. This module only guards identifiers (``sku_id``, ``intake_id``, …)
that are interpolated into filesystem paths, so a caller can never inject a path
separator or ``..`` traversal.
"""
from __future__ import annotations

import re

from fastapi import HTTPException, status

# Identifiers used inside filesystem paths must match this strict pattern.
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def validate_safe_id(value: str, field: str = "id") -> str:
    """Return ``value`` if it is a safe path component, else raise 400."""
    if not value or not SAFE_ID_PATTERN.match(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field}: must match {SAFE_ID_PATTERN.pattern}",
        )
    return value
