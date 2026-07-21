from sandbox_tests.stage2.comparison import compare_probes, compare_values


def test_comparison_allows_only_declared_numeric_tolerance():
    assert compare_values({"brightness_mean": 60.0}, {"brightness_mean": 60.009}) == []
    assert compare_values({"brightness_mean": 60.0}, {"brightness_mean": 60.02})
    assert compare_values(
        {"sharpness_laplacian_variance": 100.0},
        {"sharpness_laplacian_variance": 100.09},
    ) == []


def test_comparison_detects_fixture_or_structure_change():
    base = {
        "cases": [
            {
                "case_id": "c1",
                "category": "visual_defect",
                "input_ref": "fixture.png",
                "input_sha256": "one",
                "cv_result": {"preanalysis": {"analyzers": [{"count": 1}]}},
            }
        ]
    }
    arm = {
        "cases": [
            {
                "case_id": "c1",
                "category": "visual_defect",
                "input_ref": "fixture.png",
                "input_sha256": "two",
                "cv_result": {"preanalysis": {"analyzers": [{"count": 2}]}},
            }
        ]
    }
    result = compare_probes(base, arm)[0]
    assert result["passed"] is False
    assert "fixture sha256 differs" in result["differences"]
