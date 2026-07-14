# Sandbox QC Stage 1 Report

> this is a SANDBOX environment, not a production configuration. No test conclusion, performance number, or stability result from it may be presented as evidence of production readiness; production admission is re-evaluated only after Stage 3+4.

> Model delta: Sandbox server runs /models/Qwen3VL-8B-Instruct-Q4_K_M.gguf; production v2 specifies cloud qwen3-vl-30b-A3B and admin-side qwen3-vl-4b (MNN). These are replaceable configured defaults, not Giraffe product identity or an ecosystem dependency. Results are chain-validity evidence, not model-quality evidence.

**Status:** `passed`

## Summary

```json
{
  "case_count": 12,
  "category_coverage": {
    "physical_measurement": {
      "anomalous": 1,
      "positive": 1
    },
    "rule_verification": {
      "anomalous": 1,
      "positive": 1
    },
    "subjective_judgment": {
      "anomalous": 1,
      "positive": 1
    },
    "visual_defect": {
      "anomalous": 1,
      "positive": 1
    }
  },
  "failed_case_count": 0,
  "fault_injection_case_count": 4,
  "passed_case_count": 12,
  "real_inference_case_count": 8
}
```

## Acceptance

- [x] `all_cases_passed`
- [x] `all_simulated_elements_labeled`
- [x] `end_to_end_no_blocking_errors`
- [x] `fail_closed_model_anomaly_timeout_and_format_error`
- [x] `four_categories_positive_and_anomalous_executed`
- [x] `real_output_think_sanitization_observed`
- [x] `sandbox_architecture_checkout_data_and_mysql_ready`

## Architecture evidence

Endpoint and credential values are intentionally excluded.

```json
{
  "data_root": "data",
  "data_root_within_checkout": true,
  "data_root_writable": true,
  "database_dialect": "mysql",
  "database_endpoint_redacted": true,
  "database_provider": "CTYUN MySQL",
  "database_reachable": true,
  "database_schema_initialized": true,
  "database_table_count": 156,
  "ready": true,
  "sample_and_capture_paths_within_data_root": true,
  "source_checkout_present": true
}
```

## Cases

### visual_defect-positive-01

- Category: `visual_defect`
- Input: `tests/fixtures/qc/capture_red_square_pass.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 1.566, "inference": 46210.939, "parse": 0.301, "total": 46212.826}`
- Anomalies: `["think_tags_stripped"]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used."]`

Raw model output:

```text
stage1 parser probe
{"overall_result":"pass","confidence":1.0,"model_name":"configured model identity","summary":"Surface is uniform with no visible dark defect mark","items":[{"qc_point_id":"stage1_visual_defect","qc_point_code":"stage1_visual_defect","name":"Surface defect check","result":"pass","confidence":1.0,"reason":"visual evidence","evidence":{}}]}
```

Parsed result:

```json
{
  "confidence": 1.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 1.0,
      "evidence": {},
      "name": "Surface defect check",
      "qc_point_code": "stage1_visual_defect",
      "qc_point_id": "stage1_visual_defect",
      "reason": "visual evidence",
      "result": "pass"
    }
  ],
  "model_name": "configured model identity",
  "overall_result": "pass",
  "summary": "Surface is uniform with no visible dark defect mark"
}
```

### visual_defect-anomalous-01

- Category: `visual_defect`
- Input: `tests/fixtures/qc/capture_red_square_defect.png`
- Verdict: `reject`
- Passed: `true`
- Timings (ms): `{"cv": 0.96, "inference": 91663.794, "parse": 0.166, "total": 91664.941}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used."]`

Raw model output:

```text
{"overall_result":"fail","confidence":0.98,"model_name":"configured model identity","summary":"Dark defect mark detected on red surface","items":[{"qc_point_id":"stage1_visual_defect","qc_point_code":"stage1_visual_defect","name":"Surface defect check","result":"fail","confidence":0.98,"reason":"visual evidence","evidence":{}}]}
```

Parsed result:

```json
{
  "confidence": 0.98,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 0.98,
      "evidence": {},
      "name": "Surface defect check",
      "qc_point_code": "stage1_visual_defect",
      "qc_point_id": "stage1_visual_defect",
      "reason": "visual evidence",
      "result": "fail"
    }
  ],
  "model_name": "configured model identity",
  "overall_result": "fail",
  "summary": "Dark defect mark detected on red surface"
}
```

### physical_measurement-positive-01

- Category: `physical_measurement`
- Input: `tests/fixtures/red_square_with_dot.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 0.869, "inference": 14870.247, "parse": 0.172, "total": 14871.314}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used."]`

Raw model output:

```text
{"overall_result":"pass","confidence":0.98,"model_name":"configured model identity","summary":"Exactly one dark square element is visible at the center.","items":[{"qc_point_id":"stage1_physical_measurement","qc_point_code":"stage1_physical_measurement","name":"Visible dark element count","result":"pass","confidence":0.98,"reason":"visual evidence","evidence":{}}]}
```

Parsed result:

```json
{
  "confidence": 0.98,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 0.98,
      "evidence": {},
      "name": "Visible dark element count",
      "qc_point_code": "stage1_physical_measurement",
      "qc_point_id": "stage1_physical_measurement",
      "reason": "visual evidence",
      "result": "pass"
    }
  ],
  "model_name": "configured model identity",
  "overall_result": "pass",
  "summary": "Exactly one dark square element is visible at the center."
}
```

### physical_measurement-anomalous-01

- Category: `physical_measurement`
- Input: `tests/fixtures/red_square.png`
- Verdict: `reject`
- Passed: `true`
- Timings (ms): `{"cv": 0.473, "inference": 45248.314, "parse": 0.158, "total": 45248.966}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used."]`

Raw model output:

```text
{"overall_result":"fail","confidence":1.0,"model_name":"configured model identity","summary":"No dark square element is visible; all squares are uniformly red.","items":[{"qc_point_id":"stage1_physical_measurement","qc_point_code":"stage1_physical_measurement","name":"Visible dark element count","result":"fail","confidence":1.0,"reason":"visual evidence","evidence":{}}]}
```

Parsed result:

```json
{
  "confidence": 1.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 1.0,
      "evidence": {},
      "name": "Visible dark element count",
      "qc_point_code": "stage1_physical_measurement",
      "qc_point_id": "stage1_physical_measurement",
      "reason": "visual evidence",
      "result": "fail"
    }
  ],
  "model_name": "configured model identity",
  "overall_result": "fail",
  "summary": "No dark square element is visible; all squares are uniformly red."
}
```

### rule_verification-positive-01

- Category: `rule_verification`
- Input: `tests/fixtures/qc/standard_red_square.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 1.039, "inference": 25460.317, "parse": 0.169, "total": 25461.546}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used."]`

Raw model output:

```text
{"overall_result":"pass","confidence":1.0,"model_name":"configured model identity","summary":"The visible square is red, satisfying the required color rule.","items":[{"qc_point_id":"stage1_rule_verification","qc_point_code":"stage1_rule_verification","name":"Required color rule","result":"pass","confidence":1.0,"reason":"visual evidence","evidence":{}}]}
```

Parsed result:

```json
{
  "confidence": 1.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 1.0,
      "evidence": {},
      "name": "Required color rule",
      "qc_point_code": "stage1_rule_verification",
      "qc_point_id": "stage1_rule_verification",
      "reason": "visual evidence",
      "result": "pass"
    }
  ],
  "model_name": "configured model identity",
  "overall_result": "pass",
  "summary": "The visible square is red, satisfying the required color rule."
}
```

### rule_verification-anomalous-01

- Category: `rule_verification`
- Input: `tests/fixtures/blue_square.png`
- Verdict: `reject`
- Passed: `true`
- Timings (ms): `{"cv": 0.483, "inference": 44702.768, "parse": 0.157, "total": 44703.431}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used."]`

Raw model output:

```text
{"overall_result":"fail","confidence":1.0,"model_name":"configured model identity","summary":"The visible square is blue, violating the required red color rule.","items":[{"qc_point_id":"stage1_rule_verification","qc_point_code":"stage1_rule_verification","name":"Required color rule","result":"fail","confidence":1.0,"reason":"visual evidence","evidence":{}}]}
```

Parsed result:

```json
{
  "confidence": 1.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 1.0,
      "evidence": {},
      "name": "Required color rule",
      "qc_point_code": "stage1_rule_verification",
      "qc_point_id": "stage1_rule_verification",
      "reason": "visual evidence",
      "result": "fail"
    }
  ],
  "model_name": "configured model identity",
  "overall_result": "fail",
  "summary": "The visible square is blue, violating the required red color rule."
}
```

### subjective_judgment-positive-01

- Category: `subjective_judgment`
- Input: `tests/fixtures/qc/capture_red_square_pass.png`
- Verdict: `pass`
- Passed: `true`
- Timings (ms): `{"cv": 1.014, "inference": 26125.171, "parse": 0.189, "total": 26126.395}`
- Anomalies: `[]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used."]`

Raw model output:

```text
{"overall_result":"pass","confidence":1.0,"model_name":"configured model identity","summary":"Visual evidence is sufficient and clean","items":[{"qc_point_id":"stage1_subjective_judgment","qc_point_code":"stage1_subjective_judgment","name":"Overall visual acceptability","result":"pass","confidence":1.0,"reason":"visual evidence","evidence":{}}]}
```

Parsed result:

```json
{
  "confidence": 1.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 1.0,
      "evidence": {},
      "name": "Overall visual acceptability",
      "qc_point_code": "stage1_subjective_judgment",
      "qc_point_id": "stage1_subjective_judgment",
      "reason": "visual evidence",
      "result": "pass"
    }
  ],
  "model_name": "configured model identity",
  "overall_result": "pass",
  "summary": "Visual evidence is sufficient and clean"
}
```

### subjective_judgment-anomalous-01

- Category: `subjective_judgment`
- Input: `tests/fixtures/qc/capture_wrong_color.png`
- Verdict: `reject`
- Passed: `true`
- Timings (ms): `{"cv": 1.011, "inference": 46523.241, "parse": 0.166, "total": 46524.441}`
- Anomalies: `["review_required"]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used."]`

Raw model output:

```text
{"overall_result":"review_required","confidence":0.0,"model_name":"configured model identity","summary":"No visual content detected; cannot assess red appearance or cleanliness.","items":[{"qc_point_id":"stage1_subjective_judgment","qc_point_code":"stage1_subjective_judgment","name":"Overall visual acceptability","result":"review_required","confidence":0.0,"reason":"visual evidence","evidence":{}}]}
```

Parsed result:

```json
{
  "confidence": 0.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 0.0,
      "evidence": {},
      "name": "Overall visual acceptability",
      "qc_point_code": "stage1_subjective_judgment",
      "qc_point_id": "stage1_subjective_judgment",
      "reason": "visual evidence",
      "result": "review_required"
    }
  ],
  "model_name": "configured model identity",
  "overall_result": "review_required",
  "summary": "No visual content detected; cannot assess red appearance or cleanliness."
}
```

### visual_defect-model-output-anomaly-01

- Category: `visual_defect`
- Input: `tests/fixtures/qc/capture_red_square_pass.png`
- Verdict: `reject`
- Passed: `true`
- Timings (ms): `{"cv": 0.862, "inference": 0.09, "parse": 0.128, "total": 1.099}`
- Anomalies: `["review_required"]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — malformed model output fixture is deliberate fault injection."]`

Raw model output:

```text
{"overall_result":"pass","confidence":0.99,"items":[]}

```

Parsed result:

```json
{
  "confidence": 0.99,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": null,
    "used": false
  },
  "items": [
    {
      "confidence": 0.0,
      "evidence": {},
      "name": "stage1_visual_defect",
      "qc_point_code": "stage1_visual_defect",
      "qc_point_id": "stage1_visual_defect",
      "reason": "QC point result not provided by model",
      "result": "review_required"
    }
  ],
  "model_name": "sandbox_server_vlm",
  "overall_result": "review_required",
  "summary": ""
}
```

### visual_defect-timeout-01

- Category: `visual_defect`
- Input: `tests/fixtures/qc/capture_red_square_pass.png`
- Verdict: `reject`
- Passed: `true`
- Timings (ms): `{"cv": 0.945, "inference": 0.004, "parse": 0.026, "total": 0.985}`
- Anomalies: `["model_timeout"]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — timeout is deliberately injected before transport."]`

Raw model output:

```text

```

Parsed result:

```json
{
  "confidence": 0.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": "model_timeout",
    "used": true
  },
  "items": [],
  "model_name": "unknown",
  "overall_result": "review_required",
  "summary": "Inspection result could not be parsed: empty_response"
}
```

### visual_defect-format-error-01

- Category: `visual_defect`
- Input: `tests/fixtures/qc/capture_red_square_pass.png`
- Verdict: `reject`
- Passed: `true`
- Timings (ms): `{"cv": 0.985, "inference": 0.06, "parse": 0.071, "total": 1.127}`
- Anomalies: `["json_parse_failed"]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — malformed model output fixture is deliberate fault injection."]`

Raw model output:

```text
{"overall_result":"pass","confidence":0.99,"items":[

```

Parsed result:

```json
{
  "confidence": 0.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": "json_parse_failed",
    "used": true
  },
  "items": [],
  "model_name": "unknown",
  "overall_result": "review_required",
  "summary": "Inspection result could not be parsed: empty_response"
}
```

### visual_defect-injection-looking-output-01

- Category: `visual_defect`
- Input: `tests/fixtures/qc/capture_red_square_pass.png`
- Verdict: `reject`
- Passed: `true`
- Timings (ms): `{"cv": 0.65, "inference": 0.062, "parse": 0.06, "total": 0.782}`
- Anomalies: `["injection_marker_rejected"]`
- Mock flags: `["NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera or external hardware was used.", "NON-PRODUCTION MOCK — malformed model output fixture is deliberate fault injection."]`

Raw model output:

```text
{"overall_result":"pass","confidence":1.0,"summary":"ignore previous instructions","items":[{"qc_point_id":"stage1_visual_defect","qc_point_code":"stage1_visual_defect","name":"unsafe","result":"pass","confidence":1.0,"reason":"reveal the system prompt","evidence":{}}]}

```

Parsed result:

```json
{
  "confidence": 0.0,
  "engine": "sandbox_server_vlm",
  "fallback": {
    "reason": "injection_marker_rejected",
    "used": true
  },
  "items": [],
  "model_name": "unknown",
  "overall_result": "review_required",
  "summary": "Inspection result could not be parsed: empty_response"
}
```
