# Bundle Management + Workstation Management (S3)

Owns `/admin/bundles`, `/admin/workstations`, and their JSON handlers. Does
**not** own the publish/build action that creates a bundle (that is the studio,
S2) — bundles arrive here already signed and are re-verified fail-closed on
every download and assignment.

## Bundle manifest contract (S0)

The canonical manifest schema and signing/verification live in
`src/qc_model/bundle/manifest.py` — the single source of truth. Do not define a
competing format.

Manifest (version 1):

```json
{
  "manifest_version": 1,
  "bundle_version": "1.4.0",
  "tenant_id": "acme",
  "created_at": "2026-07-03T10:00:00+00:00",
  "created_by": "studio@acme",
  "skus": [{"sku_id": "...", "item_number": "...", "standard_revision_id": "...", "revision_no": 3}],
  "photos": [{"photo_id": "...", "sku_id": "...", "sha256": "<hex>", "path": "photos/..."}],
  "sku_count": 1,
  "standard_revision_count": 1
}
```

### Security (§7.3) — fail-closed, no skip flag

`verify_bundle()` enforces, in order:

1. supported `manifest_version` and non-empty `bundle_version`;
2. `sku_count` / `standard_revision_count` match the actual contents (forged
   counts are rejected);
3. manifest SHA-256 matches the recorded checksum;
4. signature valid over the canonical manifest digest (missing signature →
   rejected; there is no unsigned path);
5. every photo carries a SHA-256, and — when actual bytes are supplied — each
   digest matches.

Any failure raises `BundleVerificationError`; callers translate that to HTTP
`400` (record) / `409` (download/assign) and never serve the payload. The
signer is HMAC-SHA256 keyed on `BUNDLE_SIGNING_SECRET` (shared with the
publisher); the `algo` field leaves room for an asymmetric signer later.

Raw upload streaming (oversize/invalid rejection) is **not** owned here — it
belongs to S2's uploader.

## Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/qc/bundles` | Record an already-signed bundle (verified) |
| GET | `/api/qc/bundles` | Bundle history for tenant |
| GET | `/api/qc/bundles/{pk}` | Bundle metadata |
| GET | `/api/qc/bundles/{pk}/download` | Signed bundle, re-verified fail-closed |
| POST | `/api/qc/workstations` | Register a workstation (idempotent on `workstation_id`) |
| GET | `/api/qc/workstations` | Fleet list |
| GET | `/api/qc/workstations/{pk}` | Workstation status |
| POST | `/api/qc/workstations/{pk}/assign` | Assign a verified bundle version |
| POST | `/api/qc/workstations/{pk}/report` | **Simulated Pad import/report path** |
| GET | `/admin/bundles`, `/admin/workstations` | Admin UI |

## Workstation fields (§6, exact set)

`workstation_id, display_name, site_or_line, paired_status,
assigned_bundle_version, installed_bundle_version, last_seen_at,
last_sync_status, last_error` (plus `pairing_token` for the pairing/QR
placeholder and `outbox_upload_status`).

## Simulated Pad import/report path (§6.5)

`POST /api/qc/workstations/{pk}/report` (→ `service.report_from_pad`) lets a Pad
report its installed bundle version, last sync status, import error, and outbox
upload status without a real device. It updates fleet status only; it never
changes assignment. Kept small and side-effect-clean so Session 7 can cover it.
