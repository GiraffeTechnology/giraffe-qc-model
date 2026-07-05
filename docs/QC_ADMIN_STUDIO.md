# QC Admin Studio — Chat-First SKU + Standard Training (S2)

The Admin Studio is a chat-first admin surface for creating SKUs and training
their QC standard entirely from a conversation, then publishing a signed L2
bundle to the Pad. It mounts at `/admin/studio` and reuses the existing hardened
building blocks (SKU catalog, standard intake extraction/confirmation, upload
validation) rather than re-implementing them.

## Three-panel layout

| Panel | Contents |
|-------|----------|
| Left | SKU list with search + status filter |
| Center | Conversation (chat bubbles) + input (text, photo upload, voice toggle) |
| Right | SKU card, standard-photo preview, detection points, standard status, **Publish to Pad** |

Conversation bubbles follow the shared chat style: **user** messages are
right-aligned, black background, white text; **system** messages are
left-aligned, white background, black text.

## Backend routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/studio` | Three-panel Studio page |
| GET | `/admin/studio/skus` | SKU list / search (`q`) / status filter (`status`) |
| GET | `/admin/studio/skus/{sku_id}` | SKU card summary (right panel) |
| POST | `/admin/studio/chat` | Conversational SKU create + requirement extraction |
| POST | `/admin/studio/voice` | Voice toggle — returns a controlled "not enabled yet" response (never crashes) |
| POST | `/admin/studio/upload` | Standard-photo upload (hardened validation) |
| GET | `/admin/studio/photos/{photo_id}` | Serve a stored standard photo |
| POST | `/admin/studio/confirm` | Confirm candidate detection points into a standard revision |
| POST | `/admin/studio/reject` | Reject an extracted draft |
| POST | `/admin/studio/publish` | Generate + persist a signed L2 bundle |
| GET | `/admin/studio/skus/{sku_id}/bundles` | Bundle history (list UI is owned by S3) |

## Chat flow

### SKU creation (§5.2)

A message like `create sku FLW-001 Flower Brooch` creates a Draft SKU, selects
it, and shows its card. If the item number already exists the Studio selects the
existing SKU instead of duplicating it and reports its current standard status.

### Requirement extraction (§5.4)

With a SKU selected, a natural-language message is run through the deterministic
standard-intake extractor to produce candidate detection points, each carrying
the full semantic field set (`method_hint`, `expected_value`, `pass_criteria`,
`severity`). 

Counts are **never guessed**. If a countable feature is mentioned without a
number (e.g. "pearls and rhinestones"), the Studio adds a pending checkpoint with
no expected value and asks a follow-up question. Confirmation is blocked until an
expected count is supplied.

### Confirmation (§5.5)

Confirming a card persists the checkpoints into a new active standard revision
via `confirm_standard_intake`. Every semantic field — `method_hint`,
`expected_value`, and `pass_criteria` — is carried onto the persisted
`QCDetectionPoint` (a `pass_criteria` column was added in migration 017).

## Standard photo upload (§5.3)

Uploads reuse the shared hardened validator in
`src/storage/upload_validation.py`:

- **Streamed size bound** — the upload is read in chunks and aborted the moment
  it crosses `QC_MAX_UPLOAD_BYTES` (default 10 MiB), returning `413`.
- **Content sniff** — the real image type is derived from magic bytes, never
  from the client `Content-Type` or filename. Non-images are rejected with
  `415`. Supported: JPEG, PNG, WebP, BMP.

The first photo becomes the primary photo so the right-panel preview always
resolves immediately, tied to the current SKU.

## Publish → signed L2 bundle (§5.6)

`Publish to Pad` builds a bundle manifest from the active standard revision —
SKU identity, revision metadata, every detection point with its full semantic
field set, and standard-photo hashes — then signs it.

- **Manifest version**: `studio-bundle-v1`
- **Signature**: `Ed25519` over the canonical (sorted-key, compact) JSON
- **Hash**: `SHA-256` of the same canonical manifest
- Signing key: server private key (`QC_BUNDLE_SIGNING_PRIVATE_KEY_PEM` /
  `QC_BUNDLE_SIGNING_PRIVATE_KEY_PATH`); a deployed Pad verifies with only the
  public key (`QC_BUNDLE_VERIFY_PUBLIC_KEY_PEM` / `QC_BUNDLE_VERIFY_PUBLIC_KEY_PATH`)

Publishing **fails closed**: a SKU with no active revision, or an active
revision with no confirmed detection points, cannot be published (`400`). Each
publish appends one immutable row to `qc_publish_bundles`.

## Data model

Migration `017`:

- Adds `qc_detection_points.pass_criteria` (Text, nullable).
- Creates `qc_publish_bundles` — append-only signed L2 bundle history.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `QC_MAX_UPLOAD_BYTES` | `10485760` | Per-upload size ceiling |
| `QC_BUNDLE_SIGNING_PRIVATE_KEY_PEM` / `_PATH` | — (ephemeral under `APP_ENV=test`) | Ed25519 **private** signing key (server; set in production, fail-closed if absent) |
| `QC_BUNDLE_VERIFY_PUBLIC_KEY_PEM` / `_PATH` | — (derives from signer in dev/test) | Ed25519 **public** verify key (Pad/verifier) |

## Tests

`tests/test_admin_studio.py` covers each acceptance item plus the §5.1 minimum
admin happy path (FLW-001 pearl/rhinestone counts) end to end: chat SKU
creation, upload validation (accept/reject/oversize), missing-count follow-up,
confirmation persistence of all semantic fields, and signed-bundle publish with
independent signature verification.
