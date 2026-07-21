"""Deterministic extractor tests (PR 21 §5, DoD)."""
from __future__ import annotations

from src.qc_model.ingestion.extractor import PROVIDER_NAME, extract
from src.qc_model.ingestion.types import FragmentType

# Representative input crafted to exercise every fragment type.
REPRESENTATIVE_TEXT = (
    "The flower center must be aligned and centered.\n"
    "Confirm the pearl count matches the reference sample.\n"
    "Rivet diameter must be 5.0 mm plus/minus 0.2 mm.\n"
    "Reflection or glare on the surface is a capture artifact, not a defect.\n"
    "Reject if the color deviation is out of tolerance.\n"
    "Packaging label wording is TBD and needs supervisor review.\n"
    "Blorptangle frobnicator zzz.\n"
)


def test_extractor_produces_all_seven_fragment_types():
    out = extract("natural_language", REPRESENTATIVE_TEXT, None)
    seen = {f.fragment_type for f in out.fragments}
    assert seen == {t.value for t in FragmentType}
    assert out.provider == PROVIDER_NAME


def test_physical_measurement_creates_boundary_draft():
    out = extract("process_spec", "Rivet diameter must be 5.0 mm ± 0.2 mm.", None)
    frag = out.fragments[0]
    assert frag.fragment_type == FragmentType.POSSIBLE_PHYSICAL_MEASUREMENT.value
    assert frag.boundary_draft is not None
    assert frag.boundary_kind == "physical_measurement"


def test_measurement_without_number_is_missing_tolerance():
    out = extract("natural_language", "Confirm the chain link count.", None)
    assert out.fragments[0].fragment_type == FragmentType.MISSING_TOLERANCE_OR_COUNT.value


def test_detection_point_creates_requirement_draft():
    out = extract("natural_language", "The petal must not have any crack.", None)
    frag = out.fragments[0]
    assert frag.fragment_type == FragmentType.POSSIBLE_DETECTION_POINT.value
    assert frag.candidate_label == "detection_point"
    assert frag.requirement_draft is not None


def test_binary_source_yields_single_review_fragment():
    out = extract("drawing", None, "s3://bucket/drawing.pdf")
    assert len(out.fragments) == 1
    assert out.fragments[0].fragment_type == FragmentType.REQUIRES_SUPERVISOR_REVIEW.value


def test_image_source_type_is_review():
    for stype in ("image", "standard_photo", "defect_sample", "cad_export", "pdf"):
        out = extract(stype, None, "ref://x")
        assert out.fragments[0].fragment_type == FragmentType.REQUIRES_SUPERVISOR_REVIEW.value


# ── process_card (WS6) — real DIRECT_TEXT extraction + honest gating ────────


def test_process_card_plain_text_with_content_is_really_extracted():
    """A .txt process card with real text_content gets the SAME statement
    classification as a natural_language source -- not the generic binary
    fallback. This is the one genuinely real extraction path."""
    text = "The stamen must be centered and aligned.\nRivet diameter must be 5.0 mm ± 0.2 mm."
    out = extract("process_card", text, "/data/uploads/abc123.txt")
    assert len(out.fragments) == 2
    assert out.fragments[0].fragment_type == FragmentType.POSSIBLE_DETECTION_POINT.value
    assert out.fragments[1].fragment_type == FragmentType.POSSIBLE_PHYSICAL_MEASUREMENT.value


def test_process_card_unreadable_pdf_without_text_content_is_honest_not_guessed():
    """process_card.py classifies .pdf as DIRECT_TEXT-eligible, but this
    environment has no PDF parser -- extraction must say so, not fabricate
    a review fragment that looks like real extraction happened."""
    out = extract("process_card", None, "/data/uploads/abc123.pdf")
    assert len(out.fragments) == 1
    frag = out.fragments[0]
    assert frag.fragment_type == FragmentType.REQUIRES_SUPERVISOR_REVIEW.value
    assert "no readable embedded text" in frag.text
    assert "abc123.pdf" in frag.text


def test_process_card_scanned_image_reports_needs_vision_ocr():
    out = extract("process_card", None, "/data/uploads/abc123.jpg")
    frag = out.fragments[0]
    assert frag.fragment_type == FragmentType.REQUIRES_SUPERVISOR_REVIEW.value
    assert "vision OCR" in frag.text


def test_process_card_cad_reports_best_effort_needs_render():
    out = extract("process_card", None, "/data/uploads/abc123.dxf")
    frag = out.fragments[0]
    assert frag.fragment_type == FragmentType.REQUIRES_SUPERVISOR_REVIEW.value
    assert "render" in frag.text.lower()


def test_process_card_unrecognized_extension_is_unsupported_not_guessed():
    out = extract("process_card", None, "/data/uploads/abc123.xyz")
    frag = out.fragments[0]
    assert frag.fragment_type == FragmentType.REQUIRES_SUPERVISOR_REVIEW.value
    assert "refusing to guess" in frag.text.lower()
