"""Process card (工艺卡) ingestion routing (PRD Authoring Extension §1).

A process card is a manufacturing/QC routing card the admin uploads as a
standard-authoring input. It arrives in whatever format the shop floor has:

* Native electronic documents (PDF, Word, Excel, plain text) — text is directly
  extractable; no OCR needed. These feed straight into the existing §5.4
  extraction step.
* Photographed / scanned cards (JPEG, PNG, TIFF, …) — need a **vision OCR pass**
  to recover the text/layout before extraction.
* CAD exports (DWG, DXF, DGN, STEP, IGES, …) — **risk-flagged**. Most CAD
  formats are not natively text-readable by an LLM. They must be rendered to an
  image and run through the vision OCR path (or an embedded text layer pulled
  out) — and that toolchain must be *verified before being claimed as
  supported*. This module never pretends a CAD file was parsed.

This module only *classifies and routes*; it does not itself run OCR or CAD
rendering (no such toolchain is wired yet). It returns an honest plan so the
caller either (a) feeds extractable text into the deterministic extractor, or
(b) surfaces a "needs vision OCR / needs CAD render" requirement instead of
silently guessing — consistent with the no-hallucination rule (Supplement §3).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ProcessCardFormat(str, Enum):
    """Physical format of an uploaded process card."""

    ELECTRONIC_TEXT = "electronic_text"   # PDF / Word / Excel / text: text extractable
    SCANNED_IMAGE = "scanned_image"       # photo / scan: needs vision OCR
    CAD = "cad"                           # DWG / DXF / …: best-effort, needs render
    UNKNOWN = "unknown"


class IngestPath(str, Enum):
    """How the card's content should be recovered before §5.4 extraction."""

    DIRECT_TEXT = "direct_text"       # feed text straight into the extractor
    VISION_OCR = "vision_ocr"         # requires a vision OCR pass first
    CAD_RENDER = "cad_render"         # requires render-to-image then vision OCR
    UNSUPPORTED = "unsupported"


# Extension → format. Kept explicit (no wildcard guessing) so an unrecognized
# type falls through to UNKNOWN rather than being mishandled.
_ELECTRONIC_TEXT_EXT = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".md", ".rtf",
    ".odt", ".ods",
}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".heic", ".gif"}
_CAD_EXT = {".dwg", ".dxf", ".dgn", ".step", ".stp", ".iges", ".igs", ".sldprt", ".ipt", ".catpart"}

_ELECTRONIC_TEXT_MIME_PREFIXES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
    "application/vnd.ms-excel",
    "application/vnd.oasis.opendocument",
    "text/",
)


@dataclass(frozen=True)
class ProcessCardPlan:
    """The routing decision for one uploaded process card."""

    fmt: ProcessCardFormat
    path: IngestPath
    # True only when text can be handed to the deterministic extractor right now
    # (either inline text was supplied, or a native-text document was provided).
    text_ready: bool
    # A risk flag the UI must surface before claiming the card is "supported".
    best_effort: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "format": self.fmt.value,
            "path": self.path.value,
            "text_ready": self.text_ready,
            "best_effort": self.best_effort,
            "reason": self.reason,
        }


def _ext(filename: Optional[str]) -> str:
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


def classify_process_card(
    *,
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> ProcessCardFormat:
    """Classify a process card's physical format from filename/mime.

    Filename extension wins when present (most reliable on the shop floor);
    mime type is the fallback. Unrecognized → :attr:`ProcessCardFormat.UNKNOWN`.
    """
    ext = _ext(filename)
    if ext in _CAD_EXT:
        return ProcessCardFormat.CAD
    if ext in _ELECTRONIC_TEXT_EXT:
        return ProcessCardFormat.ELECTRONIC_TEXT
    if ext in _IMAGE_EXT:
        return ProcessCardFormat.SCANNED_IMAGE

    mime = (mime_type or "").lower()
    if mime:
        if mime.startswith("image/"):
            return ProcessCardFormat.SCANNED_IMAGE
        if any(mime.startswith(p) for p in _ELECTRONIC_TEXT_MIME_PREFIXES):
            return ProcessCardFormat.ELECTRONIC_TEXT
        # A few CAD mime types exist but are rare/nonstandard; match loosely.
        if "dxf" in mime or "dwg" in mime or "step" in mime or "iges" in mime:
            return ProcessCardFormat.CAD
    return ProcessCardFormat.UNKNOWN


def plan_process_card_ingestion(
    *,
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
    has_inline_text: bool = False,
) -> ProcessCardPlan:
    """Decide how a process card should be turned into extractable text.

    ``has_inline_text`` is True when the caller already holds usable text for
    the card (e.g. an electronic doc's text layer was pulled out upstream). In
    that case the plan is always DIRECT_TEXT regardless of the declared format.
    """
    if has_inline_text:
        return ProcessCardPlan(
            fmt=classify_process_card(filename=filename, mime_type=mime_type),
            path=IngestPath.DIRECT_TEXT,
            text_ready=True,
            best_effort=False,
            reason="Inline text provided; routing directly into §5.4 extraction.",
        )

    fmt = classify_process_card(filename=filename, mime_type=mime_type)
    if fmt is ProcessCardFormat.ELECTRONIC_TEXT:
        return ProcessCardPlan(
            fmt=fmt,
            path=IngestPath.DIRECT_TEXT,
            text_ready=True,
            best_effort=False,
            reason="Native electronic document — extract embedded text, no OCR needed.",
        )
    if fmt is ProcessCardFormat.SCANNED_IMAGE:
        return ProcessCardPlan(
            fmt=fmt,
            path=IngestPath.VISION_OCR,
            text_ready=False,
            best_effort=False,
            reason="Photographed/scanned card — a vision OCR pass is required before extraction.",
        )
    if fmt is ProcessCardFormat.CAD:
        return ProcessCardPlan(
            fmt=fmt,
            path=IngestPath.CAD_RENDER,
            text_ready=False,
            best_effort=True,
            reason=(
                "CAD export — not natively LLM-readable. Render to an image and "
                "run the vision OCR path (or pull any embedded text layer). "
                "Best-effort: verify the actual toolchain before claiming CAD "
                "process cards are supported."
            ),
        )
    return ProcessCardPlan(
        fmt=ProcessCardFormat.UNKNOWN,
        path=IngestPath.UNSUPPORTED,
        text_ready=False,
        best_effort=True,
        reason="Unrecognized process-card format; refusing to guess its contents.",
    )


__all__ = [
    "ProcessCardFormat",
    "IngestPath",
    "ProcessCardPlan",
    "classify_process_card",
    "plan_process_card_ingestion",
]
