from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.cv_preanalysis import (
    PreanalysisError,
    build_prompt_block,
    run_preanalysis,
    write_evidence,
    write_overlay,
)


FIXTURE = Path(__file__).parent / "fixtures" / "cv_preanalysis_fixture.pgm"
EXPECTED = FIXTURE.with_name("cv_preanalysis_fixture.expected.json")


def test_rhinestone_count_golden_fixture_and_deviation():
    result = run_preanalysis(
        FIXTURE,
        {
            "analyzers": ["rhinestone_count"],
            "parameters": {
                "highlight_threshold": 220,
                "morphology_kernel_px": 1,
                "min_area_px": 3,
                "max_area_px": 20,
                "min_circularity": 0.2,
            },
        },
        {"rhinestone_count": 3},
    )
    analysis = result["analyzers"][0]
    assert analysis == json.loads(EXPECTED.read_text())
    assert result["deviations"] == [
        {"feature": "rhinestone_count", "expected": 3, "actual": 2}
    ]
    assert result["verdict_effect"] == "informational_only"


def test_rhinestone_negative_fixture_is_zero():
    black = np.zeros((32, 32, 3), dtype=np.uint8)
    result = run_preanalysis(black, {"analyzers": ["rhinestone_count"]})
    assert result["analyzers"][0]["count"] == 0
    assert result["analyzers"][0]["confidence"] == 0.0


def test_petal_segmentation_golden_and_negative():
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    cv2.ellipse(image, (22, 40), (12, 24), 0, 0, 360, (255, 0, 255), -1)
    cv2.ellipse(image, (58, 40), (12, 24), 0, 0, 360, (255, 0, 255), -1)
    result = run_preanalysis(
        image,
        {"analyzers": ["petal_segmentation"], "parameters": {"min_area_px": 100}},
    )["analyzers"][0]
    assert result["count"] == 2
    assert all(len(polygon) >= 4 for polygon in result["polygons"])
    negative = run_preanalysis(
        np.zeros_like(image), {"analyzers": ["petal_segmentation"]}
    )["analyzers"][0]
    assert negative["count"] == 0


def test_pistil_localization_golden_and_negative():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(image, (50, 48), 10, (0, 255, 255), -1)
    result = run_preanalysis(image, {"analyzers": ["pistil_localization"]})["analyzers"][0]
    assert result["found"] is True
    assert result["center"] == {"x": 0.5, "y": 0.48}
    assert result["box"] == {"x": 0.4, "y": 0.38, "w": 0.21, "h": 0.21}
    negative = run_preanalysis(
        np.zeros_like(image), {"analyzers": ["pistil_localization"]}
    )["analyzers"][0]
    assert negative["found"] is False


def test_prompt_block_is_canonical_and_evidence_is_persisted(tmp_path):
    analysis = run_preanalysis(FIXTURE, {"analyzers": ["rhinestone_count"]})
    block = build_prompt_block(analysis)
    assert block.startswith("<CV_PREANALYSIS_JSON>\n{")
    assert block.endswith("independently inspect the image.")
    ref = write_evidence(
        tmp_path, request_id="req/unsafe", point_code="stones front", analysis=analysis
    )
    assert Path(ref).name == "stones_front.cv.json"
    assert json.loads(Path(ref).read_text()) == analysis
    overlay = write_overlay(
        tmp_path, request_id="req/unsafe", point_code="stones front", image=FIXTURE, analysis=analysis
    )
    assert Path(overlay).name == "stones_front.cv-overlay.png"
    assert cv2.imread(overlay) is not None


def test_bad_config_and_decode_are_explicit_failures():
    with pytest.raises(PreanalysisError, match="non-empty"):
        run_preanalysis(FIXTURE, {"analyzers": []})
    with pytest.raises(PreanalysisError, match="decoded"):
        run_preanalysis("/missing/image.jpg", {"analyzers": ["rhinestone_count"]})


def test_studio_authored_analyzer_schema_runs_with_per_analyzer_params():
    result = run_preanalysis(
        FIXTURE,
        {
            "analyzers": [{
                "name": "rhinestone_count",
                "params": {
                    "highlight_threshold": 220,
                    "morphology_kernel_px": 1,
                    "min_area_px": 3,
                    "max_area_px": 20,
                    "min_circularity": 0.2,
                },
            }],
        },
        {"rhinestone_count": 3},
    )
    assert result["analyzers"][0] == json.loads(EXPECTED.read_text())
    assert result["deviations"][0]["actual"] == 2


def test_studio_authored_analyzer_schema_rejects_bad_params():
    with pytest.raises(PreanalysisError, match="params must be an object"):
        run_preanalysis(
            FIXTURE,
            {"analyzers": [{"name": "rhinestone_count", "params": "bad"}]},
        )
