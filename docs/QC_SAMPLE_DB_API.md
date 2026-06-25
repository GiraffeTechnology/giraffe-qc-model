# QC Sample Database & SKU API

This document describes the QC sample catalog database schema and the
Android-compatible REST API for SKU search and inspection data.

## Overview

The SKU catalog stores the reference information the Android Pad needs to:

1. Search and select a sample to inspect
2. Display the standard reference photo
3. Present inspection requirements to the operator
4. Define detection points / QC focus areas

The sample DB and SKU API are **shared by the Pad edition and the Server
edition**. Neither the schema nor the API branches by edition.

## Database Tables

### `qc_sku_items` — SKU / Sample Master

| Column | Type | Notes |
|---|---|---|
| `id` | String(64) PK | Internal stable identifier (hex UUID) |
| `tenant_id` | String(64) | Defaults to `"default"` |
| `item_number` | String(128) | Operator-facing code, searchable |
| `name` | String(256) | Human-readable name, searchable |
| `category` | String(128) | Optional grouping |
| `description` | Text | Optional description |
| `status` | String(32) | `active` \| `inactive` \| `archived` |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

**Unique constraint:** `(tenant_id, item_number)` — the same item number
cannot be created twice within the same tenant. A duplicate create returns
HTTP 409.

Only `status=active` records are returned by the search API.

### `qc_standard_photos` — Reference Photo Metadata

| Column | Type | Notes |
|---|---|---|
| `id` | String(64) PK | |
| `tenant_id` | String(64) | |
| `sku_id` | FK → qc_sku_items | |
| `image_url` | String(512) | HTTP URL served by the backend |
| `local_path` | String(512) | Factory filesystem path |
| `thumbnail_url` | String(512) | Optional thumbnail |
| `angle` | String(64) | e.g. `front`, `back`, `side` |
| `view_type` | String(64) | e.g. `standard`, `defect_example` |
| `sha256` | String(64) | Optional integrity hash |
| `width_px` | Integer | Optional |
| `height_px` | Integer | Optional |
| `mime_type` | String(128) | Optional |
| `is_primary` | Boolean | Primary photo used in search response |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

**Photo storage modes:**

- **Mode A (file upload):** Files are stored at
  `data/qc_samples/{tenant_id}/{sku_id}/photos/{filename}`. `local_path` is
  set to the stored path. `sha256`, `mime_type`, `width_px`, and `height_px`
  are computed automatically from the uploaded bytes.
- **Mode B (URL / path registration):** Provide `image_url` (HTTP) or
  `local_path` (factory filesystem path) directly. No file is stored locally.

The `data/qc_samples/` directory is listed in `.gitignore` — uploaded
images are never committed to git.

**Primary photo:** When `is_primary=true` is set on a new photo, the backend
clears the previous primary photo for that SKU and tenant. The clearing
query filters by both `sku_id` **and** `tenant_id` to prevent cross-tenant
data mutations.

### `qc_inspection_requirements` — Pass/Fail Criteria

| Column | Type | Notes |
|---|---|---|
| `id` | String(64) PK | |
| `tenant_id` | String(64) | |
| `sku_id` | FK → qc_sku_items | |
| `code` | String(64) | e.g. `REQ-STAIN-001` |
| `title` | String(256) | Short title |
| `requirement_text` | Text | Full requirement description |
| `severity` | String(32) | `minor` \| `major` \| `critical` |
| `pass_criteria` | Text | Quantitative pass threshold |
| `tolerance_json` | JSON | Optional structured tolerance |
| `sort_order` | Integer | Display order |
| `is_active` | Boolean | Inactive requirements hidden from detail API |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

Examples:
- `REQ-STAIN-001`: No visible stain on front surface
- `REQ-COLOR-001`: Flower stem color must match reference photo
- `REQ-CLIP-BENT-001`: Hair clip metal part must not be bent
- `REQ-SEAM-001`: Fabric seam must be straight within tolerance

### `qc_detection_points` — Inspection Focus Areas

| Column | Type | Notes |
|---|---|---|
| `id` | String(64) PK | |
| `tenant_id` | String(64) | |
| `sku_id` | FK → qc_sku_items | |
| `requirement_id` | FK → qc_inspection_requirements (nullable) | |
| `point_code` | String(64) | e.g. `DP-FLOWER-FRONT-001` |
| `label` | String(256) | Short display label |
| `description` | Text | Detailed description |
| `roi_json` | JSON | Normalized coordinates `{x,y,w,h}` ∈ [0,1] |
| `expected_value` | String(256) | Optional expected result description |
| `method_hint` | String(128) | Optional inspection method hint |
| `severity` | String(32) | `minor` \| `major` \| `critical` |
| `sort_order` | Integer | Display order |
| `is_active` | Boolean | |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

ROI coordinates use normalized [0,1] values:
```json
{"x": 0.10, "y": 0.20, "w": 0.30, "h": 0.25}
```

Detection points are inspection definitions / expected focus areas, not
MNN model outputs.

## Data Integrity

### Unique SKU item number per tenant

The DB carries a unique constraint `uq_sku_tenant_item_number` on
`(tenant_id, item_number)`. The API pre-checks for duplicates before insert
and returns HTTP 409 if the combination already exists. An `IntegrityError`
catch provides a secondary safeguard against races.

Different tenants may share the same `item_number`.

### Primary photo tenant safety

When clearing the previous primary photo before setting a new one, the
query filters by **both** `sku_id` and `tenant_id`. This prevents a primary
photo belonging to one tenant from being inadvertently cleared by an
operation on a different tenant.

## API Endpoints

All endpoints use prefix `/api/v1/sku`.

### Search SKU

```
GET /api/v1/sku/search?q={query}&tenant_id=default
```

Searches `item_number` and `name` (case-insensitive, substring match).
Only `status=active` SKUs are returned. Empty `q` returns empty list.
`tenant_id` defaults to `"default"` if omitted.

**Response (Android-compatible):**
```json
{
  "items": [
    {
      "id": "sku-flower-001",
      "item_number": "ITEM-FLOWER-001",
      "name": "Artificial Flower A",
      "reference_image_url": "http://192.168.1.10:8080/assets/ref/sku-flower-001-front.jpg",
      "standard_photo_path": "/factory/ref/sku-flower-001-front.jpg"
    }
  ]
}
```

### Get SKU Detail

```
GET /api/v1/sku/{sku_id}?tenant_id=default
```

**Response:**
```json
{
  "id": "sku-flower-001",
  "item_number": "ITEM-FLOWER-001",
  "name": "Artificial Flower A",
  "category": "artificial_flower",
  "description": "Standard inspection sample for artificial flower A",
  "reference_image_url": "http://192.168.1.10:8080/assets/ref/sku-flower-001-front.jpg",
  "standard_photo_path": "/factory/ref/sku-flower-001-front.jpg",
  "photos": [
    {
      "id": "photo-flower-001-front",
      "image_url": "http://192.168.1.10:8080/assets/ref/sku-flower-001-front.jpg",
      "local_path": "/factory/ref/sku-flower-001-front.jpg",
      "angle": "front",
      "view_type": "standard",
      "sha256": "e3b0c..."
    }
  ],
  "inspection_requirements": [
    {
      "id": "req-flower-001",
      "code": "REQ-STAIN-001",
      "title": "No visible stain",
      "requirement_text": "No visible stain on front visible surface",
      "severity": "major",
      "pass_criteria": "No stain larger than 2mm on the front surface"
    }
  ],
  "detection_points": [
    {
      "id": "dp-flower-001",
      "point_code": "DP-FLOWER-FRONT-001",
      "label": "Front surface stain check",
      "description": "Check visible front surface for stain",
      "roi_json": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
      "severity": "major"
    }
  ]
}
```

### Create SKU

```
POST /api/v1/sku
```

```json
{
  "tenant_id": "default",
  "item_number": "ITEM-FLOWER-001",
  "name": "Artificial Flower A",
  "category": "artificial_flower",
  "description": "Standard inspection sample"
}
```

Returns **HTTP 409** if `(tenant_id, item_number)` already exists.

### Add Standard Photo

```
POST /api/v1/sku/{sku_id}/photos
```

```json
{
  "tenant_id": "default",
  "image_url": "http://192.168.1.10:8080/assets/ref/sku-001-front.jpg",
  "local_path": "/factory/ref/sku-001-front.jpg",
  "angle": "front",
  "view_type": "standard",
  "sha256": "optional",
  "is_primary": true
}
```

If `is_primary=true`, the backend clears the existing primary photo for this
SKU and tenant before setting the new one.

### Add Inspection Requirement

```
POST /api/v1/sku/{sku_id}/requirements
```

```json
{
  "tenant_id": "default",
  "code": "REQ-STAIN-001",
  "title": "No visible stain",
  "requirement_text": "No visible stain on visible surface",
  "severity": "major",
  "pass_criteria": "No stain larger than 2mm",
  "sort_order": 1
}
```

### Add Detection Point

```
POST /api/v1/sku/{sku_id}/detection-points
```

```json
{
  "tenant_id": "default",
  "requirement_id": "req-flower-001",
  "point_code": "DP-FRONT-001",
  "label": "Front surface stain check",
  "description": "Check visible front surface for stain",
  "roi_json": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
  "severity": "major",
  "sort_order": 1
}
```

## Seed Data

Three SKUs are pre-seeded via `scripts/seed_qc_sample_data.py`:

| item_number | name | category |
|---|---|---|
| `ITEM-FLOWER-001` | Artificial Flower A | artificial_flower |
| `ITEM-HAIRCLIP-001` | Hair Clip Standard | accessory |
| `ITEM-BRACELET-001` | Bracelet Standard | jewelry |

Each has: 1 primary standard photo, 2 inspection requirements, 2 detection points.

To seed:
```bash
uv run python scripts/seed_qc_sample_data.py
```

To seed against a different DB:
```bash
QC_DB_URL=postgresql://... uv run python scripts/seed_qc_sample_data.py
```

## Android Compatibility

The search response shape matches the `ApiSkuRepository` contract:

```kotlin
// Android parses:
data class SkuItem(
    val id: String,
    val item_number: String,
    val name: String,
    val reference_image_url: String?,
    val standard_photo_path: String?
)
data class SkuSearchResponse(val items: List<SkuItem>)
```

The Android app currently calls:
- `GET /api/v1/sku/search?q={query}` — for task selection search
- `GET /api/v1/sku/{sku_id}` — for SKU detail (optional, for future iterations)

Neither call requires `tenant_id`; the backend defaults to `"default"`.

## Quick Smoke Test

```bash
# Start backend
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8080

# Seed data
uv run python scripts/seed_qc_sample_data.py

# Health check
curl http://127.0.0.1:8080/health
# {"status":"ok"}

# Search
curl "http://127.0.0.1:8080/api/v1/sku/search?q=FLOWER"
# {"items":[{"id":"sku-flower-001","item_number":"ITEM-FLOWER-001",...}]}

# Detail
curl http://127.0.0.1:8080/api/v1/sku/sku-flower-001
# {"id":"sku-flower-001","photos":[...],"inspection_requirements":[...], ...}

# Admin UI
# Open http://127.0.0.1:8080/admin/samples in a browser
```

## Related Documentation

- `docs/QC_SAMPLE_ADMIN_UI.md` — admin web interface for managing samples
- `docs/ANDROID_QC_APP.md` — Android app module and SKU API integration
