"""Tests for CVComparator — pure computer-vision QC without LLM."""
import cv2
import numpy as np
import pytest
from src.cv.comparator import CVComparator
from src.llm.base import ImageCompareResult, LLMProvider

# ── Helpers shared across tests ───────────────────────────────────────────────


# ── Helpers ───────────────────────────────────────────────────────────────────

def _solid(path, bgr, size=(100, 100)):
    img = np.zeros((*size, 3), dtype=np.uint8)
    img[:] = bgr
    cv2.imwrite(str(path), img)
    return str(path)


def _with_dot(path, bgr, dot_size=30, size=(100, 100)):
    img = np.zeros((*size, 3), dtype=np.uint8)
    img[:] = bgr
    cy, cx = size[0] // 2, size[1] // 2
    d = dot_size // 2
    img[cy - d:cy + d, cx - d:cx + d] = (0, 0, 0)
    cv2.imwrite(str(path), img)
    return str(path)


@pytest.fixture
def comp():
    return CVComparator()


@pytest.fixture
def red(tmp_path):
    return _solid(tmp_path / "red.png", (0, 0, 200))


@pytest.fixture
def blue(tmp_path):
    return _solid(tmp_path / "blue.png", (200, 0, 0))


@pytest.fixture
def red_dot(tmp_path):
    return _with_dot(tmp_path / "red_dot.png", (0, 0, 200), dot_size=30)


# ── Interface contract ────────────────────────────────────────────────────────

class TestCVComparatorInterface:
    def test_provider_name(self, comp):
        assert comp.provider_name == "cv"

    def test_is_llm_provider_subclass(self, comp):
        assert isinstance(comp, LLMProvider)

    def test_returns_image_compare_result(self, comp, red):
        r = comp.compare_images([red], [red])
        assert isinstance(r, ImageCompareResult)

    def test_http_status_always_200(self, comp, red):
        assert comp.compare_images([red], [red]).http_status == 200

    def test_elapsed_ms_non_negative(self, comp, red):
        assert comp.compare_images([red], [red]).elapsed_ms >= 0

    def test_similarity_always_in_range(self, comp, red, blue):
        for a, b in [(red, red), (red, blue), (blue, red)]:
            r = comp.compare_images([a], [b])
            assert 0.0 <= r.similarity_score <= 1.0

    def test_overall_result_valid_enum(self, comp, red, blue):
        for a, b in [(red, red), (red, blue)]:
            assert comp.compare_images([a], [b]).overall_result in (
                "pass", "needs_fix", "reject", "unknown"
            )


# ── Verdicts ──────────────────────────────────────────────────────────────────

class TestCVComparatorVerdicts:
    def test_identical_images_pass(self, comp, red):
        r = comp.compare_images([red], [red])
        assert r.overall_result == "pass"
        assert r.similarity_score >= 0.85

    def test_different_colours_reject(self, comp, red, blue):
        r = comp.compare_images([red], [blue])
        assert r.overall_result == "reject"
        assert r.similarity_score < 0.6

    def test_small_defect_not_pass(self, comp, red, red_dot):
        r = comp.compare_images([red], [red_dot])
        assert r.overall_result in ("needs_fix", "reject")

    def test_large_defect_reject(self, comp, tmp_path):
        std  = _solid(tmp_path / "std.png", (0, 0, 200), size=(200, 200))
        prod = np.zeros((200, 200, 3), dtype=np.uint8)
        prod[:] = (0, 0, 200)
        prod[50:150, 50:150] = (0, 0, 0)   # 100×100 = 25 % area
        pp = str(tmp_path / "prod_big.png")
        cv2.imwrite(pp, prod)
        assert comp.compare_images([std], [pp]).overall_result == "reject"

    def test_deviations_populated_on_colour_fail(self, comp, red, blue):
        r = comp.compare_images([red], [blue])
        assert len(r.deviations) > 0
        assert any(d["field"] == "colour" for d in r.deviations)

    def test_feedback_strings_populated(self, comp, red, blue):
        r = comp.compare_images([red], [blue])
        assert isinstance(r.feedback_zh, str) and len(r.feedback_zh) > 5
        assert isinstance(r.feedback_en, str) and len(r.feedback_en) > 5

    def test_pass_has_empty_deviations(self, comp, red):
        r = comp.compare_images([red], [red])
        assert r.deviations == []


# ── Missing image handling ────────────────────────────────────────────────────

class TestCVComparatorMissingFiles:
    def test_missing_standard_raises(self, comp, tmp_path):
        prod = _solid(tmp_path / "prod.png", (0, 0, 200))
        with pytest.raises(FileNotFoundError):
            comp.compare_images(["/no/such/std.png"], [prod])

    def test_missing_production_raises(self, comp, tmp_path):
        std = _solid(tmp_path / "std.png", (0, 0, 200))
        with pytest.raises(FileNotFoundError):
            comp.compare_images([std], ["/no/such/prod.png"])

    def test_both_missing_raises_not_pass(self, comp):
        with pytest.raises(FileNotFoundError):
            comp.compare_images(["/no/a.png"], ["/no/b.png"])

    def test_empty_paths_raises(self, comp):
        with pytest.raises(FileNotFoundError):
            comp.compare_images([], [])


# ── Registry integration ──────────────────────────────────────────────────────

class TestRegistryCV:
    def test_get_provider_default_is_cv(self):
        from src.llm.registry import get_provider
        assert get_provider().provider_name == "cv"

    def test_get_provider_cv_explicit(self):
        from src.llm.registry import get_provider
        assert get_provider("cv").provider_name == "cv"

    def test_raises_when_llm_enabled_but_no_key(self, monkeypatch):
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        from src.llm.registry import get_provider
        with pytest.raises(ValueError, match="no API key"):
            get_provider("qwen")

    def test_silent_fallback_when_llm_disabled(self, monkeypatch):
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "false")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        from src.llm.registry import get_provider
        assert get_provider("qwen").provider_name == "cv"
