"""Upload hardening helpers: MIME whitelist, size cap, path sanitization.

Shared by every route that accepts an image upload so the same limits apply
everywhere. Validation is fail-closed: anything not positively recognized as an
allowed image within the size limit is rejected.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from fastapi import HTTPException, UploadFile, status

# Chunk size for bounded streaming reads (1 MiB).
_READ_CHUNK_BYTES = 1024 * 1024

# Allowed image MIME types (task A3).
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}

# Map allowed MIME -> canonical file extension for safe storage.
MIME_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# Identifiers used inside filesystem paths (sku_id, intake_id, ...) must match
# this strict pattern so a caller can never inject path separators or ``..``.
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

_DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def max_upload_bytes() -> int:
    """Configurable max upload size (bytes); default 10 MB."""
    raw = os.getenv("MAX_UPLOAD_BYTES")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return _DEFAULT_MAX_UPLOAD_BYTES


def validate_safe_id(value: str, field: str = "id") -> str:
    """Return ``value`` if it is a safe path component, else raise 400.

    Guards against path traversal via user-controlled identifiers used to build
    storage paths (e.g. ``sku_id`` containing ``../``).
    """
    if not value or not SAFE_ID_PATTERN.match(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field}: must match {SAFE_ID_PATTERN.pattern}",
        )
    return value


def _sniff_mime(content: bytes) -> Optional[str]:
    """Best-effort content-based MIME detection for the allowed image types."""
    if len(content) < 12:
        return None
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image_upload(
    content: bytes,
    declared_mime: Optional[str],
    *,
    max_bytes: Optional[int] = None,
) -> str:
    """Validate an uploaded image's size and MIME. Return the canonical MIME.

    * Empty upload → 400.
    * Over the size limit → 413.
    * Declared or sniffed MIME not in the whitelist → 415.

    The returned MIME is the content-sniffed type when available (so a spoofed
    ``Content-Type`` cannot smuggle a disallowed payload), otherwise the
    declared type once it is confirmed to be in the whitelist.
    """
    limit = max_bytes if max_bytes is not None else max_upload_bytes()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty upload",
        )
    if len(content) > limit:
        raise HTTPException(
            status_code=413,  # Content Too Large
            detail=f"File too large: {len(content)} bytes exceeds limit of {limit} bytes",
        )

    sniffed = _sniff_mime(content)
    if sniffed is not None:
        # Content is authoritative; if a declared type contradicts it, reject.
        if declared_mime and declared_mime.lower() not in ALLOWED_IMAGE_MIME:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported media type: {declared_mime}",
            )
        return sniffed

    # Could not identify content as an allowed image → reject.
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(
            "Unsupported media type: only "
            + ", ".join(sorted(ALLOWED_IMAGE_MIME))
            + " are allowed"
        ),
    )


def extension_for_mime(mime: str) -> str:
    return MIME_EXTENSION.get(mime, ".bin")


async def read_upload_limited(
    upload: UploadFile, max_bytes: Optional[int] = None
) -> bytes:
    """Read an UploadFile in chunks, rejecting oversize input *while streaming*.

    Unlike ``await upload.read()`` (which loads the entire body into memory before
    any size check), this reads at most ``max_bytes + one chunk`` and raises 413 as
    soon as the accumulated size exceeds the limit — so a huge upload can never
    exhaust worker memory before validation returns. The upload is rewound to the
    start on the way out so downstream code can re-read if needed.

    Returns the fully-read bytes when within the limit.
    """
    limit = max_bytes if max_bytes is not None else max_upload_bytes()
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = await upload.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise HTTPException(
                    status_code=413,  # Content Too Large
                    detail=f"File too large: exceeds limit of {limit} bytes",
                )
            chunks.append(chunk)
    finally:
        # Best-effort rewind so a later reader isn't left at EOF.
        try:
            await upload.seek(0)
        except Exception:
            pass
    return b"".join(chunks)
