# QC API Contract

All endpoints are prefixed with `/api/v1`. Cross-tenant access returns HTTP 404.

## Authentication

Every `/api/v1/sku` and `/api/v1/qc` request must be authenticated (the same
gate that protects `/admin` and `/api/qc`). Two credential shapes are accepted:

- **Signed bearer token** — `Authorization: Bearer <token>` minted by
  `src.api.auth.mint_token`.
- **Static API key** — `X-API-Key: <key>` provisioned through the
  `QC_API_KEYS` environment map (`key -> {"tenant_id": ..., "admin": bool}`)
  for machine clients (Pad, Jetson runner) that cannot mint signed tokens.

The effective tenant is always the authenticated principal's tenant. A
caller-supplied `tenant_id` query parameter or JSON body field is overwritten
by the gate and never trusted. Unauthenticated requests receive HTTP 401;
non-admin principals receive HTTP 403.

## Product Standards

| Method | Path                                       | Description                        |
|--------|--------------------------------------------|------------------------------------|
| POST   | `/standards/`                              | Create a product standard          |
| GET    | `/standards/{standard_id}`                 | Get standard (tenant-scoped)       |
| GET    | `/standards/`                              | List standards for tenant          |
| GET    | `/standards/{standard_id}/photos`          | List standard photos               |
| POST   | `/standards/{standard_id}/photos`          | Upload a standard photo            |

## QC Points

| Method | Path                                       | Description                        |
|--------|--------------------------------------------|------------------------------------|
| POST   | `/standards/{standard_id}/qc-points`       | Add QC point to standard           |
| GET    | `/standards/{standard_id}/qc-points`       | List QC points                     |

## Inspections

| Method | Path                                       | Description                        |
|--------|--------------------------------------------|------------------------------------|
| POST   | `/inspections/`                            | Create inspection run              |
| GET    | `/inspections/{inspection_id}`             | Get inspection (tenant-scoped)     |
| POST   | `/inspections/{inspection_id}/capture`     | Upload capture photo               |
| POST   | `/inspections/{inspection_id}/result`      | Submit inspection result           |
| GET    | `/inspections/{inspection_id}/items`       | List per-QC-point results          |

## Captures

| Method | Path                                       | Description                        |
|--------|--------------------------------------------|------------------------------------|
| POST   | `/captures/`                               | Record a capture                   |
| GET    | `/captures/{capture_id}`                   | Get capture (tenant-scoped)        |

## Assets

| Method | Path                                       | Description                        |
|--------|--------------------------------------------|------------------------------------|
| POST   | `/assets/`                                 | Register a QC asset                |
| GET    | `/assets/{asset_id}`                       | Get asset (tenant-scoped)          |
| GET    | `/assets/`                                 | List assets for tenant/SKU         |

## Sync

| Method | Path                                       | Description                        |
|--------|--------------------------------------------|------------------------------------|
| POST   | `/sync/jobs`                               | Enqueue a sync job                 |
| GET    | `/sync/jobs/{job_id}`                      | Get sync job status                |

## Response Codes

| Code | Meaning                                        |
|------|------------------------------------------------|
| 200  | Success                                        |
| 201  | Created                                        |
| 400  | Bad request (validation failure)               |
| 401  | Missing or invalid credential                  |
| 403  | Authenticated but not authorized (non-admin)   |
| 404  | Not found or cross-tenant access denied        |
| 422  | Unprocessable entity (schema error)            |
| 500  | Internal server error                          |

## Result Schema

```json
{
  "overall_result": "pass | fail | review_required",
  "engine": "local_qwen_mnn | cloud_qwen | router",
  "model_name": "Qwen2-VL-2B-Instruct-MNN",
  "confidence": 0.95,
  "summary": "All QC points passed.",
  "fallback": { "used": false, "reason": null },
  "items": [
    {
      "qc_point_id": "QC-01",
      "qc_point_code": "color_check",
      "name": "Color",
      "result": "pass",
      "confidence": 0.97,
      "reason": "Color matches standard within tolerance.",
      "evidence": {}
    }
  ]
}
```

## Tenant Isolation

Every database query filters by `tenant_id`. Accessing a resource owned by a different tenant returns HTTP 404 (not 403), to avoid leaking resource existence.
