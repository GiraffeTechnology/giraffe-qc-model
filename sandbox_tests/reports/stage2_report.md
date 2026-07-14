# Sandbox QC Stage 2 Report

> this is a SANDBOX environment, not a production configuration. No test conclusion, performance number, or stability result from it may be presented as evidence of production readiness; production admission is re-evaluated only after Stage 3+4.

> Model delta: Stage 2 CV/UI simulation requires no real LLM/VLM call. Sandbox and production model selections remain replaceable configured defaults, not Giraffe product identity or ecosystem dependencies. Qwen is one configured default, not a required product ecosystem. This report contains no model-quality evidence.

**Status:** `passed`

## Summary

```json
{
  "arm64_guest_verified": true,
  "case_count": 14,
  "cv_case_count": 8,
  "failed_case_count": 0,
  "model_call_count": 0,
  "passed_case_count": 14,
  "simulation_method": "qemu_aarch64",
  "ui_case_count": 6
}
```

## Acceptance

- [x] `simulation_method_recorded`
- [x] `external_drive_rw_stable`
- [x] `cv_module_complete_without_arch_or_dependency_error`
- [x] `stage1_stage2_difference_list_complete`
- [x] `simulation_limitations_recorded`
- [x] `ui_validation_complete`
- [x] `all_cases_passed`

## Cases

### stage2-physical_measurement-anomalous-01

- Category: `physical_measurement`
- Input: `tests/fixtures/red_square.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "arm64_cv_result": {
    "brightness_mean": 103.38,
    "input_height_px": 100,
    "input_width_px": 100,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "pistil_localization",
          "box": null,
          "center": null,
          "confidence": 0.0,
          "found": false
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 15998.4639,
    "verdict_effect": "informational_only"
  },
  "input_sha256": "3b84497769e2380cd7e20520cfa950a0633f55701d3c7af1f92a42abd0f4405c",
  "native_cv_result": {
    "brightness_mean": 103.38,
    "input_height_px": 100,
    "input_width_px": 100,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "pistil_localization",
          "box": null,
          "center": null,
          "confidence": 0.0,
          "found": false
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 15998.4639,
    "verdict_effect": "informational_only"
  },
  "within_declared_tolerance": true
}
```

### stage2-physical_measurement-positive-01

- Category: `physical_measurement`
- Input: `tests/fixtures/red_square_with_dot.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "arm64_cv_result": {
    "brightness_mean": 99.2448,
    "input_height_px": 100,
    "input_width_px": 100,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "pistil_localization",
          "box": {
            "h": 0.2,
            "w": 0.2,
            "x": 0.4,
            "y": 0.4
          },
          "center": {
            "x": 0.495,
            "y": 0.495
          },
          "confidence": 0.7444,
          "found": true
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 15867.5751,
    "verdict_effect": "informational_only"
  },
  "input_sha256": "9307a4f8e12dbdff8d3477558d2fbc739f6288b05c8f2f544a0048786ef222ea",
  "native_cv_result": {
    "brightness_mean": 99.2448,
    "input_height_px": 100,
    "input_width_px": 100,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "pistil_localization",
          "box": {
            "h": 0.2,
            "w": 0.2,
            "x": 0.4,
            "y": 0.4
          },
          "center": {
            "x": 0.495,
            "y": 0.495
          },
          "confidence": 0.7444,
          "found": true
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 15867.5751,
    "verdict_effect": "informational_only"
  },
  "within_declared_tolerance": true
}
```

### stage2-rule_verification-anomalous-01

- Category: `rule_verification`
- Input: `tests/fixtures/blue_square.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "arm64_cv_result": {
    "brightness_mean": 52.0,
    "input_height_px": 100,
    "input_width_px": 100,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "petal_segmentation",
          "area_fractions": [],
          "confidence": 0.0,
          "count": 0,
          "polygons": []
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "input_sha256": "5645654ba08011b4be90fd2fa7adf66c1fc7b97d3e53c068d8382961689a7c46",
  "native_cv_result": {
    "brightness_mean": 52.0,
    "input_height_px": 100,
    "input_width_px": 100,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "petal_segmentation",
          "area_fractions": [],
          "confidence": 0.0,
          "count": 0,
          "polygons": []
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "within_declared_tolerance": true
}
```

### stage2-rule_verification-positive-01

- Category: `rule_verification`
- Input: `tests/fixtures/qc/standard_red_square.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "arm64_cv_result": {
    "brightness_mean": 60.0,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "petal_segmentation",
          "area_fractions": [
            0.99
          ],
          "confidence": 0.99,
          "count": 1,
          "polygons": [
            [
              {
                "x": 0.0,
                "y": 0.0
              },
              {
                "x": 0.0,
                "y": 0.995
              },
              {
                "x": 0.995,
                "y": 0.995
              },
              {
                "x": 0.995,
                "y": 0.0
              }
            ]
          ]
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "input_sha256": "c6f40751a149c3a5c9787119d16fd51575e85cc57852289e9f4f23178aa76a73",
  "native_cv_result": {
    "brightness_mean": 60.0,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "petal_segmentation",
          "area_fractions": [
            0.99
          ],
          "confidence": 0.99,
          "count": 1,
          "polygons": [
            [
              {
                "x": 0.0,
                "y": 0.0
              },
              {
                "x": 0.0,
                "y": 0.995
              },
              {
                "x": 0.995,
                "y": 0.995
              },
              {
                "x": 0.995,
                "y": 0.0
              }
            ]
          ]
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "within_declared_tolerance": true
}
```

### stage2-subjective_judgment-anomalous-01

- Category: `subjective_judgment`
- Input: `tests/fixtures/qc/capture_wrong_color.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "arm64_cv_result": {
    "brightness_mean": 23.0,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "petal_segmentation",
          "area_fractions": [],
          "confidence": 0.0,
          "count": 0,
          "polygons": []
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "input_sha256": "fd72eb96db02e5274c1dd4a03d691e6bf742541fa2c2d632842d898c28c5d78a",
  "native_cv_result": {
    "brightness_mean": 23.0,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "petal_segmentation",
          "area_fractions": [],
          "confidence": 0.0,
          "count": 0,
          "polygons": []
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "within_declared_tolerance": true
}
```

### stage2-subjective_judgment-positive-01

- Category: `subjective_judgment`
- Input: `tests/fixtures/qc/capture_red_square_pass.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "arm64_cv_result": {
    "brightness_mean": 60.0,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "petal_segmentation",
          "area_fractions": [
            0.99
          ],
          "confidence": 0.99,
          "count": 1,
          "polygons": [
            [
              {
                "x": 0.0,
                "y": 0.0
              },
              {
                "x": 0.0,
                "y": 0.995
              },
              {
                "x": 0.995,
                "y": 0.995
              },
              {
                "x": 0.995,
                "y": 0.0
              }
            ]
          ]
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "input_sha256": "c6f40751a149c3a5c9787119d16fd51575e85cc57852289e9f4f23178aa76a73",
  "native_cv_result": {
    "brightness_mean": 60.0,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "petal_segmentation",
          "area_fractions": [
            0.99
          ],
          "confidence": 0.99,
          "count": 1,
          "polygons": [
            [
              {
                "x": 0.0,
                "y": 0.0
              },
              {
                "x": 0.0,
                "y": 0.995
              },
              {
                "x": 0.995,
                "y": 0.995
              },
              {
                "x": 0.995,
                "y": 0.0
              }
            ]
          ]
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "within_declared_tolerance": true
}
```

### stage2-visual_defect-anomalous-01

- Category: `visual_defect`
- Input: `tests/fixtures/qc/capture_red_square_defect.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "arm64_cv_result": {
    "brightness_mean": 57.6,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "rhinestone_count",
          "backend": "contour",
          "boxes": [],
          "centers": [],
          "confidence": 0.0,
          "count": 0
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 29.52,
    "verdict_effect": "informational_only"
  },
  "input_sha256": "dabafd7eb4881be6ee00303c0630ab8a2f307c4baafd6b7762c963a07842f16b",
  "native_cv_result": {
    "brightness_mean": 57.6,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "rhinestone_count",
          "backend": "contour",
          "boxes": [],
          "centers": [],
          "confidence": 0.0,
          "count": 0
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 29.52,
    "verdict_effect": "informational_only"
  },
  "within_declared_tolerance": true
}
```

### stage2-visual_defect-positive-01

- Category: `visual_defect`
- Input: `tests/fixtures/qc/capture_red_square_pass.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "arm64_cv_result": {
    "brightness_mean": 60.0,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "rhinestone_count",
          "backend": "contour",
          "boxes": [],
          "centers": [],
          "confidence": 0.0,
          "count": 0
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "input_sha256": "c6f40751a149c3a5c9787119d16fd51575e85cc57852289e9f4f23178aa76a73",
  "native_cv_result": {
    "brightness_mean": 60.0,
    "input_height_px": 200,
    "input_width_px": 200,
    "preanalysis": {
      "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
      "analyzers": [
        {
          "analyzer": "rhinestone_count",
          "backend": "contour",
          "boxes": [],
          "centers": [],
          "confidence": 0.0,
          "count": 0
        }
      ],
      "deviations": [],
      "schema_version": "1.0",
      "verdict_effect": "informational_only"
    },
    "sharpness_laplacian_variance": 0.0,
    "verdict_effect": "informational_only"
  },
  "within_declared_tolerance": true
}
```

### stage2-ui-simulator-ready

- Category: `subjective_judgment`
- Input: `sandbox_tests/reports/evidence/stage2/ui/simulator-ready.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — UI state is driven by Stage 2 simulation evidence.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "fail_closed": false,
  "inference_call_count": 0,
  "mock_label_visible": true,
  "qemu_aarch64_label_visible": true,
  "result_count": 0,
  "screenshot_height_px": 1800,
  "screenshot_width_px": 2560,
  "status": "READY"
}
```

### stage2-ui-simulated-capture

- Category: `subjective_judgment`
- Input: `sandbox_tests/reports/evidence/stage2/ui/simulated-capture.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — UI state is driven by Stage 2 simulation evidence.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "fail_closed": false,
  "inference_call_count": 0,
  "mock_label_visible": true,
  "qemu_aarch64_label_visible": true,
  "result_count": 0,
  "screenshot_height_px": 1800,
  "screenshot_width_px": 2560,
  "status": "FIXTURE LOADED"
}
```

### stage2-ui-cv-success

- Category: `subjective_judgment`
- Input: `sandbox_tests/reports/evidence/stage2/ui/cv-success.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — UI state is driven by Stage 2 simulation evidence.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "fail_closed": false,
  "inference_call_count": 0,
  "mock_label_visible": true,
  "qemu_aarch64_label_visible": true,
  "result_count": 1,
  "screenshot_height_px": 1800,
  "screenshot_width_px": 2560,
  "status": "CV COMPLETE"
}
```

### stage2-ui-cv-anomaly

- Category: `subjective_judgment`
- Input: `sandbox_tests/reports/evidence/stage2/ui/cv-anomaly.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — UI state is driven by Stage 2 simulation evidence.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "fail_closed": true,
  "inference_call_count": 0,
  "mock_label_visible": true,
  "qemu_aarch64_label_visible": true,
  "result_count": 0,
  "screenshot_height_px": 1800,
  "screenshot_width_px": 2560,
  "status": "REVIEW REQUIRED"
}
```

### stage2-ui-simulator-unavailable

- Category: `subjective_judgment`
- Input: `sandbox_tests/reports/evidence/stage2/ui/simulator-unavailable.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — UI state is driven by Stage 2 simulation evidence.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "fail_closed": true,
  "inference_call_count": 0,
  "mock_label_visible": true,
  "qemu_aarch64_label_visible": true,
  "result_count": 0,
  "screenshot_height_px": 1800,
  "screenshot_width_px": 2560,
  "status": "BLOCKED"
}
```

### stage2-ui-refresh-retry

- Category: `subjective_judgment`
- Input: `sandbox_tests/reports/evidence/stage2/ui/refresh-retry.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — UI state is driven by Stage 2 simulation evidence.", "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "after_screenshot": "sandbox_tests/reports/evidence/stage2/ui/refresh-retry.png",
  "before_screenshot": "sandbox_tests/reports/evidence/stage2/ui/simulator-unavailable.png",
  "event_log": "sandbox_tests/reports/evidence/stage2/ui/refresh-retry-events.log",
  "fail_closed": false,
  "inference_call_count": 0,
  "mock_label_visible": true,
  "qemu_aarch64_label_visible": true,
  "result_count": 1,
  "screenshot_height_px": 1800,
  "screenshot_width_px": 2560,
  "status": "RETRY COMPLETE"
}
```
