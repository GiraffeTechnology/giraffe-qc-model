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

This module classifies and routes, and performs deterministic embedded-text
extraction for the minimum supported electronic formats. Image OCR is handled
by the provider-neutral Studio vision gateway; CAD rendering remains explicitly
unsupported until a verified renderer is deployed.
"""
from __future__ import annotations

import os
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from xml.etree import ElementTree


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

# Public aliases so callers that need to validate an upload's extension
# (e.g. src.storage.upload_validation) share this list instead of
# maintaining a second copy that can drift.
ELECTRONIC_TEXT_EXTENSIONS = frozenset(_ELECTRONIC_TEXT_EXT)
IMAGE_EXTENSIONS = frozenset(_IMAGE_EXT)
CAD_EXTENSIONS = frozenset(_CAD_EXT)
ALL_PROCESS_CARD_EXTENSIONS = ELECTRONIC_TEXT_EXTENSIONS | IMAGE_EXTENSIONS | CAD_EXTENSIONS

# Formats with a real extraction implementation below. Legacy binary Word/Excel
# files remain accepted for storage but are not presented as parsed.
REAL_TEXT_EXTRACTION_EXTENSIONS = frozenset({
    ".txt", ".md", ".csv", ".pdf", ".docx", ".xlsx",
})

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
        ext = _ext(filename)
        supported = ext in REAL_TEXT_EXTRACTION_EXTENSIONS
        return ProcessCardPlan(
            fmt=fmt,
            path=IngestPath.DIRECT_TEXT,
            text_ready=supported,
            best_effort=not supported,
            reason=(
                "Native electronic document — embedded text extraction is available."
                if supported else
                "Electronic format is stored, but no verified embedded-text parser is available."
            ),
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


def _clean_text(value: str) -> str | None:
    lines = [" ".join(line.split()) for line in value.replace("\x00", "").splitlines()]
    text = "\n".join(line for line in lines if line).strip()
    return text[:2_000_000] or None


def _decode_plain(content: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return _clean_text(content.decode(encoding))
        except UnicodeDecodeError:
            continue
    return None


def _docx_text(content: bytes) -> str | None:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return None
    paragraphs: list[str] = []
    for paragraph in root.iter():
        if not paragraph.tag.endswith("}p"):
            continue
        text = "".join(
            node.text or "" for node in paragraph.iter() if node.tag.endswith("}t")
        ).strip()
        if text:
            paragraphs.append(text)
    return _clean_text("\n".join(paragraphs))


def _xlsx_text(content: bytes) -> str | None:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = set(archive.namelist())
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in root.iter():
                    if item.tag.endswith("}si"):
                        shared.append("".join(
                            node.text or "" for node in item.iter() if node.tag.endswith("}t")
                        ))
            rows: list[str] = []
            for name in sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")):
                root = ElementTree.fromstring(archive.read(name))
                for row in (node for node in root.iter() if node.tag.endswith("}row")):
                    values: list[str] = []
                    for cell in (node for node in row if node.tag.endswith("}c")):
                        cell_type = cell.attrib.get("t")
                        inline = "".join(
                            node.text or "" for node in cell.iter() if node.tag.endswith("}t")
                        )
                        raw = next(
                            (node.text or "" for node in cell.iter() if node.tag.endswith("}v")), ""
                        )
                        if cell_type == "s" and raw.isdigit() and int(raw) < len(shared):
                            values.append(shared[int(raw)])
                        elif inline:
                            values.append(inline)
                        elif raw:
                            values.append(raw)
                    if values:
                        rows.append("\t".join(values))
    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return None
    return _clean_text("\n".join(rows))


def extract_process_card_text(path: str | Path) -> str | None:
    """Extract real embedded text, returning None on unreadable/empty input."""
    source = Path(path)
    extension = source.suffix.lower()
    try:
        content = source.read_bytes()
    except OSError:
        return None
    if extension in {".txt", ".md", ".csv"}:
        return _decode_plain(content)
    if extension == ".docx":
        return _docx_text(content)
    if extension == ".xlsx":
        return _xlsx_text(content)
    if extension == ".pdf":
        try:
            completed = subprocess.run(
                ["pdftotext", "-layout", str(source), "-"],
                capture_output=True,
                check=False,
                timeout=20,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return _decode_plain(completed.stdout)
    return None


__all__ = [
    "ProcessCardFormat",
    "IngestPath",
    "ProcessCardPlan",
    "classify_process_card",
    "plan_process_card_ingestion",
    "extract_process_card_text",
    "REAL_TEXT_EXTRACTION_EXTENSIONS",
]
