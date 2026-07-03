# Offline Standard Sync (Task 03)

Server ↔ Pad synchronization for the QC "digital inspector". QC engineers train
SKU standards on the server; those standards reach the **offline** production Pad
as **self-contained, versioned, signed bundles**, and completed inspection
results flow back to the server during sync windows.

> **Real-time push is NOT supported by design.** The production-line Pad is
> offline during inspection — there is no live server connection while jobs run.
> "Pushing" a standard means delivering a signed bundle during a sync window or
> via USB sideload; the Pad imports it fail-closed. No code path requires the
> network during inspection.

## 1. Standard Bundle format

A bundle is a single **`.tar.gz`** archive:

| Member | Contents |
|--------|----------|
| `manifest.json` | Canonical UTF-8 JSON: `bundle_format_version`, `bundle_version` (monotonic per tenant+line), `generated_at`, `tenant_id`, `line_scope`, `signing_key_fingerprint`, `sku_count`, and `skus[]`. Each SKU carries `sku_id`, `item_number`, `name`, `category`, `active_standard_revision_id`, `revision_no`, `detection_points[]`, `inspection_requirements[]`, and `photos[]` (each with the archive-relative `path`). |
| `photos/<sku_id>/<file>` | Standard reference photo files for every included SKU. |
| `checksum.sha256` | `sha256sum`-format line per file: `manifest.json` + every photo. |
| `bundle.sig` | Base64 Ed25519 signature over `manifest.json` bytes + `"\n"` + `checksum.sha256` bytes. |

Only **ACTIVE** standard revisions are exported; draft / pending / archived
revisions never ship (no-guess).

**Idempotent & monotonic.** Re-importing the same `bundle_version` is a no-op.
Importing a `bundle_version` lower than what is installed is **rejected**
(downgrade protection). An override flag is reserved but intentionally not
implemented.

### Signature chain of trust

The signature covers `manifest.json` **and** `checksum.sha256`, and the checksum
file covers every photo. Therefore:

- tamper a photo → its checksum no longer matches → **rejected**;
- also rewrite `checksum.sha256` to match the bad photo → the signature over the
  checksum bytes no longer verifies → **rejected**;
- tamper `manifest.json` → signature (and its checksum entry) fail → **rejected**.

## 2. Signing & key management

Ed25519 via the `cryptography` library.

**Server (private key)** — configured by environment; validated at startup in the
server edition (a configured-but-invalid key fails startup loudly; set
`QC_BUNDLE_SIGNING_REQUIRED=true` to also fail when no key is configured). Only
key *fingerprints* are logged, never key material.

| Env var | Meaning |
|---------|---------|
| `QC_BUNDLE_SIGNING_KEY` | Path to a PEM Ed25519 private key. |
| `QC_BUNDLE_SIGNING_KEY_PEM` | Inline PEM private key (secret manager). |
| `QC_BUNDLE_PUBLIC_KEY` / `_PEM` | Optional explicit verify-side public key. |
| `QC_BUNDLE_STORE_DIR` | Where built archives are stored (default `data/bundles`). |

**Pad (public key)** — the raw 32-byte Ed25519 public key, base64, ships as the
app asset `apps/android-qc/app/src/main/assets/qc_bundle_public_key.b64` and is
replaceable via an app update. **Verification is mandatory — there is no
"skip verification" flag in production builds** (Hard Constraint 3). The Pad
verifies the signature on the outer envelope *before* parsing any manifest
content. Provision the matching public key with
`GET /api/v1/qc/bundles/public-key`.

> The public key currently committed is a development default. Replace it with
> the production public key (whose private half is held only by the server) before
> deployment.

## 3. Delivery channels (same bundle format)

1. **Sync-window pull (primary).** When the Pad has network (shift change / office
   Wi-Fi) a user-initiated Sync action calls `GET /api/v1/qc/bundles/latest`,
   compares versions, downloads if newer, verifies, and imports. Implemented by
   `PadSyncManager.pullLatest`.
2. **USB sideload (fallback).** A bundle file is copied into
   `/sdcard/giraffe_qc/inbox/`. `InboxScanner` detects it, funnels it through the
   **same** `BundleImporter`, and moves it to `processed/` or `failed/` with a log
   record. No network involved.

Both channels converge on one importer, so verification and fail-closed behavior
are identical.

## 4. Import (Pad), fail-closed

`BundleImporter.import` order — prior standards survive any failure:

1. verify signature + per-file checksums + manifest (`BundleVerification`);
2. downgrade / idempotency check vs. the installed version;
3. confirm every manifest-referenced photo is present (reject partial archives);
4. extract photos to app-scoped storage keyed by bundle version;
5. transactional `StandardStore.installBundle` (all-or-nothing; a mid-import
   failure rolls back and the previous standards stay active).

A SKU with no imported standard cannot start an inspection (no standard → no
inspection), consistent with the existing `PadInspectionCoordinator` fail-closed
rules.

## 5. Reverse sync: result outbox (Pad → Server)

Completed jobs queue in a local SQLite outbox during offline production
(`OutboxStore`), then upload in batches during a sync window
(`OutboxUploader` → `POST /api/v1/qc/inspection-jobs/batch`).

- **Built on the generation-3 pipeline** (`qc_inspection_jobs` + checkpoint
  results + media + final report). The legacy generation-2
  `sync_targets`/`sync_jobs` tables are **not** touched.
- **Idempotent.** The Pad supplies a client-generated job UUID as the job id.
  Re-upload of the same UUID is a server-side no-op (`duplicate`) — never a second
  job.
- **Resumable.** Uploads are per-batch atomic; a network failure leaves the
  remaining jobs `pending` for the next window. Job records upload first; media is
  referenced by path/sha256 and uploaded separately.
- The outbox never blocks or alters inspection operation; failed uploads retry on
  the next window.

## 6. API summary

| Method & path | Purpose |
|---------------|---------|
| `POST /api/v1/qc/bundles/export` | Build + sign a bundle from ACTIVE revisions; returns metadata. |
| `GET /api/v1/qc/bundles/latest` | Sync-window version check. |
| `GET /api/v1/qc/bundles/history` | Bundle history (version, generated_at, sku_count, downloaded_by). |
| `GET /api/v1/qc/bundles/{id}/download` | Download the signed archive. |
| `GET /api/v1/qc/bundles/public-key` | Ed25519 public key for Pad provisioning. |
| `POST /api/v1/qc/inspection-jobs/batch` | Idempotent Pad→Server result upload. |

Tenant is derived from the caller's credential (Task 02 auth). Until Task 02
lands, tenant is taken from the request via the single seam
`qc_sync_router._resolve_tenant`.
