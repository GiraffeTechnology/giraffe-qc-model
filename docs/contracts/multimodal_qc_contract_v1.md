# Multimodal QC Contract v1

**Contract version string:** `multimodal-qc-v1`

This document is the authoritative specification for the QC inspection result schema shared between the main server (Python) and the Android Pad app (Kotlin). Both sides must embed `contract_version: "multimodal-qc-v1"` in every request and response. A version mismatch must be logged and surfaced to the caller — never silently accepted.

---

## 1. Canonical Result Values

Only three result strings are valid at any scope (overall and per-item):

| Value | Meaning |
|---|---|
| `pass` | QC point or overall inspection passed |
| `fail` | QC point or overall inspection failed (defect confirmed) |
| `review_required` | Uncertain; human review or retry required |

**Forbidden values** (never appear in any production result): `ok`, `ng`, `unknown`, `needs_fix`, `good`, `bad`.

Any unrecognised value received from a provider must be normalised to `review_required` (fail-closed). Never normalise to `pass`.

---

## 2. Fail-Closed Policy

- Missing image → `review_required` (never `pass`)
- Model unavailable / not provisioned → `review_required`
- JSON parse error → `review_required`
- Timeout → `review_required`
- Network error (backend proxy) → `review_required`
- Hallucinated QC point ID (not in request) → rejected
- Missing QC point ID (in request, absent from response) → filled as `review_required`
- On-device `fail` result is final — no cloud escalation, no backend proxy escalation

---

## 3. Request Schema

```json
{
  "contract_version": "multimodal-qc-v1",
  "tenant_id": "string",
  "sku_id": "string",
  "standard_id": "string",
  "inspection_id": "string",
  "standard_image_paths": ["string"],
  "captured_image_path": "string",
  "qc_points": [
    {
      "qc_point_id": "string",
      "qc_point_code": "string",
      "name": "string",
      "description": "string",
      "roi_json": "string | null",
      "rule_type": "string | null"
    }
  ]
}
```

---

## 4. Result Schema

See `multimodal_qc_result_schema_v1.json` for the JSON Schema definition.

```json
{
  "contract_version": "multimodal-qc-v1",
  "overall_result": "pass | fail | review_required",
  "engine": "string",
  "provider": "string",
  "model_name": "string",
  "confidence": 0.0,
  "items": [
    {
      "qc_point_id": "string",
      "qc_point_code": "string",
      "name": "string",
      "result": "pass | fail | review_required",
      "confidence": 0.0,
      "reason": "string"
    }
  ],
  "fallback": {
    "used": false,
    "reason": "string | null"
  },
  "summary": "string"
}
```

---

## 5. Version Handshake

Server and Pad both embed `QC_CONTRACT_VERSION = "multimodal-qc-v1"` as a constant:

- **Python (server):** `src/multimodal/contract.py` → `QC_CONTRACT_VERSION`
- **Kotlin (Pad):** `SharedQcContract.QC_CONTRACT_VERSION`

A schema migration bumps the version string in both constants simultaneously. The new version travels in a new contract document (`multimodal_qc_contract_v2.md`) and schema file.

---

## 6. Provider Routing (Server)

The server selects a provider via `MULTIMODAL_PROVIDER` env var. Default is `qwen`.
`MULTIMODAL_ENABLE_REAL_CALLS=false` forces `MockProvider` regardless of the env var.

Valid providers: `qwen`, `openai`, `anthropic`, `local_mnn`, `local_server`, `cv`, `mock`.

## 7. Provider Routing (Pad)

Pad provider priority:
1. `LocalMnnInspector` (on-device MNN, default primary)
2. `BackendProxyInspector` (HTTP to server, `PAD_ALLOW_BACKEND_PROXY=true` required)
3. `MockInspector` (CI/test only)

`PAD_ALLOW_DIRECT_CLOUD` must always be `false`. The Pad never calls cloud providers directly.
