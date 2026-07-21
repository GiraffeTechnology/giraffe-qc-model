"""Tests for process-card (工艺卡) ingestion routing (PRD Authoring Extension §1).

- Electronic docs (PDF/Word/Excel/text) route directly into §5.4 extraction.
- Photographed/scanned cards require a vision OCR pass.
- CAD exports are risk-flagged best-effort (render-then-OCR), never claimed
  parsed.
- process_card is a recognized source type.
"""
from __future__ import annotations

import subprocess
import zipfile
from io import BytesIO

import pytest

from src.qc_model.ingestion.types import QCSourceType, is_valid_source_type
from src.qc_model.ingestion.process_card import (
    IngestPath,
    ProcessCardFormat,
    classify_process_card,
    extract_process_card_text,
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


def test_docx_embedded_text_is_really_extracted(tmp_path):
    target = tmp_path / "card.docx"
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="urn:w"><w:body>'
            '<w:p><w:r><w:t>The stamen must be centered.</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Rivet tolerance is 0.2 mm.</w:t></w:r></w:p>'
            '</w:body></w:document>',
        )
    target.write_bytes(payload.getvalue())
    assert extract_process_card_text(target) == (
        "The stamen must be centered.\nRivet tolerance is 0.2 mm."
    )


def test_xlsx_shared_string_and_number_are_really_extracted(tmp_path):
    target = tmp_path / "card.xlsx"
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?><sst xmlns="urn:x"><si><t>Expected count</t></si></sst>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="urn:x"><sheetData><row>'
            '<c t="s"><v>0</v></c><c><v>8</v></c>'
            '</row></sheetData></worksheet>',
        )
    target.write_bytes(payload.getvalue())
    assert extract_process_card_text(target) == "Expected count 8"


def test_pdf_uses_real_pdftotext_output_and_fails_closed(monkeypatch, tmp_path):
    target = tmp_path / "card.pdf"
    target.write_bytes(b"%PDF-1.4")

    def success(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout=b"Center aligned\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", success)
    assert extract_process_card_text(target) == "Center aligned"

    def failure(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout=b"", stderr=b"bad")

    monkeypatch.setattr(subprocess, "run", failure)
    assert extract_process_card_text(target) is None
