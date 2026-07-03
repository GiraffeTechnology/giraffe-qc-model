"""Hardened image-upload validation shared by every QC upload surface.

Two guarantees, applied before any bytes touch disk or the DB:

1. **Streamed size bound** — the upload is read chunk-by-chunk and aborted the
   instant it crosses the configured byte ceiling, so a hostile client cannot
   force the process to buffer an unbounded file in memory.
2. **Content sniff (magic bytes)** — the real image type is derived from the
   leading bytes, never from the client-supplied ``Content-Type`` or filename.
   A declared ``image/png`` that is actually an executable is rejected.

This is intentionally the *only* place upload bytes are vetted; callers (Pad
upload, Sample Admin, Admin Studio standard-photo upload) reuse it rather than
re-implementing their own limits and sniffers.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_STREAM_CHUNK = 64 * 1024


def max_upload_bytes() -> int:
    """Ceiling for a single upload, read at call time so tests can override."""
    raw = os.getenv("QC_MAX_UPLOAD_BYTES")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return _DEFAULT_MAX_BYTES


# mime -> canonical extension.  Only real, still-image raster formats are
# accepted for a QC standard photo.
_ALLOWED_IMAGE_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


class UploadValidationError(Exception):
    """Raised when an upload fails a size or content check.

    ``status_code`` maps to the HTTP status the caller should return
    (413 for too-large, 400/415 for a rejected content type).
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedImage:
    """Result of a successful validation."""
    content: bytes
    mime_type: str
    extension: str
    sha256: str
    size_bytes: int


def sniff_image_mime(head: bytes) -> Optional[str]:
    """Return the image MIME type implied by leading magic bytes, or None.

    Detection is based purely on the file signature — client headers are
    ignored.  ``head`` should be at least the first 16 bytes of the payload.
    """
    if len(head) >= 3 and head[0:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 8 and head[0:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if len(head) >= 2 and head[0:2] == b"BM":
        return "image/bmp"
    return None


def validate_image_content(
    content: bytes,
    *,
    declared_content_type: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> ValidatedImage:
    """Validate an already-buffered image payload.

    Enforces the size ceiling and the magic-byte sniff.  ``declared_content_type``
    is accepted only for logging/parity — the returned ``mime_type`` always comes
    from the sniff, never from the caller-supplied header.
    """
    limit = max_bytes if max_bytes is not None else max_upload_bytes()
    if not content:
        raise UploadValidationError("Uploaded file is empty.", status_code=400)
    if len(content) > limit:
        raise UploadValidationError(
            f"Uploaded file is too large ({len(content)} bytes > {limit} byte limit).",
            status_code=413,
        )

    sniffed = sniff_image_mime(content[:16])
    if sniffed is None:
        raise UploadValidationError(
            "Uploaded file is not a supported image (JPEG, PNG, WebP, or BMP).",
            status_code=415,
        )
    if sniffed not in _ALLOWED_IMAGE_MIME:  # pragma: no cover - defensive
        raise UploadValidationError(
            f"Image type {sniffed!r} is not permitted.", status_code=415
        )

    return ValidatedImage(
        content=content,
        mime_type=sniffed,
        extension=_ALLOWED_IMAGE_MIME[sniffed],
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )


async def read_and_validate_upload(
    upload,
    *,
    max_bytes: Optional[int] = None,
) -> ValidatedImage:
    """Stream a FastAPI ``UploadFile`` under a hard size bound, then validate.

    Reads in ``_STREAM_CHUNK`` slices and aborts as soon as the accumulated size
    exceeds the ceiling — the whole payload is never held beyond the limit.
    """
    limit = max_bytes if max_bytes is not None else max_upload_bytes()
    buffer = bytearray()
    while True:
        chunk = await upload.read(_STREAM_CHUNK)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise UploadValidationError(
                f"Uploaded file exceeds the {limit} byte limit.",
                status_code=413,
            )
    return validate_image_content(
        bytes(buffer),
        declared_content_type=getattr(upload, "content_type", None),
        max_bytes=limit,
    )
