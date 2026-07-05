"""Tests for process-card (工艺卡) ingestion routing (PRD Authoring Extension §1).

- Electronic docs (PDF/Word/Excel/text) route directly into §5.4 extraction.
- Photographed/scanned cards require a vision OCR pass.
- CAD exports are risk-flagged best-effort (render-then-OCR), never claimed
  parsed.
- process_card is a recognized source type.
"""
from __future__ import annotations

import pytest

from src.qc_model.ingestion.types import QCSourceType, is_valid_source_type
from src.qc_model.ingestion.process_card import (
    IngestPath,
    ProcessCardFormat,
    classify_process_card,
    plan_process_card_ingestion,
)


def test_process_card_is_valid_source_type():
    assert is_valid_source_type("process_card")
    assert QCSourceType.PROCESS_CARD.value == "process_card"


@pytest.mark.parametrize("name", ["card.pdf", "spec.docx", "sheet.xlsx", "notes.txt", "data.csv"])
def test_electronic_docs_route_direct_text(name):
    plan = plan_process_card_ingestion(filename=name)
    assert plan.fmt is ProcessCardFormat.ELECTRONIC_TEXT
    assert plan.path is IngestPath.DIRECT_TEXT
    assert plan.text_ready is True
    assert plan.best_effort is False


@pytest.mark.parametrize("name", ["card.jpg", "scan.png", "photo.tiff", "img.heic"])
def test_images_route_vision_ocr(name):
    plan = plan_process_card_ingestion(filename=name)
    assert plan.fmt is ProcessCardFormat.SCANNED_IMAGE
    assert plan.path is IngestPath.VISION_OCR
    assert plan.text_ready is False


@pytest.mark.parametrize("name", ["part.dwg", "drawing.dxf", "model.step", "assy.iges"])
def test_cad_is_best_effort_flagged(name):
    plan = plan_process_card_ingestion(filename=name)
    assert plan.fmt is ProcessCardFormat.CAD
    assert plan.path is IngestPath.CAD_RENDER
    assert plan.best_effort is True
    assert plan.text_ready is False
    assert "verify" in plan.reason.lower()


def test_inline_text_always_direct_regardless_of_format():
    # Even a scanned image is DIRECT_TEXT if upstream already OCR'd it.
    plan = plan_process_card_ingestion(filename="scan.png", has_inline_text=True)
    assert plan.path is IngestPath.DIRECT_TEXT
    assert plan.text_ready is True


def test_unknown_format_is_unsupported_not_guessed():
    plan = plan_process_card_ingestion(filename="mystery.xyz")
    assert plan.fmt is ProcessCardFormat.UNKNOWN
    assert plan.path is IngestPath.UNSUPPORTED
    assert plan.text_ready is False


def test_mime_type_fallback_when_no_extension():
    assert classify_process_card(mime_type="application/pdf") is ProcessCardFormat.ELECTRONIC_TEXT
    assert classify_process_card(mime_type="image/jpeg") is ProcessCardFormat.SCANNED_IMAGE


def test_extension_wins_over_mime():
    # Filename extension is the more reliable signal on the shop floor.
    assert classify_process_card(filename="x.dwg", mime_type="image/png") is ProcessCardFormat.CAD
