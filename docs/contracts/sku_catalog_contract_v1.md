# SKU Catalog Contract v1

**Note:** This document defines the abstract interface for SKU catalog lookups used by the
QC pipeline. The database schema and API endpoints for the SKU catalog are defined and
implemented by PR #7 (`feat: add QC SKU catalog DB models and Android-compatible SKU API`,
branch `claude/qc-sample-db-sku-api-6h2w1l`). This contract document must not duplicate
that work.

---

## 1. Purpose

The QC pipeline needs SKU metadata to:
- Resolve a `sku_id` to its set of standard image references
- Look up QC points associated with a `standard_id`
- Match a candidate SKU against the catalog during `sku_match` capability execution

---

## 2. Lookup Interface

The multimodal pipeline consumes SKU data through the following abstract interface.
Implementations may be backed by the SQLite DB (PR #7), a mock, or a future REST catalog.

### 2.1 SKU Resolution

**Input:** `sku_id: str`, `standard_id: str`

**Output:**
```json
{
  "sku_id": "string",
  "standard_id": "string",
  "standard_image_paths": ["string"],
  "qc_points": [
    {
      "qc_point_id": "string",
      "qc_point_code": "string",
      "name": "string",
      "description": "string"
    }
  ]
}
```

**Error:** If `sku_id` or `standard_id` is not found, the caller must treat it as
`review_required` — never as `pass`.

### 2.2 SKU Match Candidate

During `sku_match` capability execution, the provider returns `SkuMatchResult`
(see `multimodal_qc_result_schema_v1.json` and `src/multimodal/types.py`).
The pipeline validates that `top_candidates[].sku_id` values exist in the catalog;
hallucinated SKU IDs are rejected.

---

## 3. Versioning

This contract document tracks the abstract lookup interface version.
The underlying DB schema version is owned by PR #7 and its migration history.
Bumping this document's version requires updating both the Python interface and
the Kotlin `BackendProxyInspector` request builder.
