# Configuration Web UI — Sample Intake & Digital Inspector Training

This is the PC-facing admin tool used by QC engineers to configure a SKU's
inspection standard. It extends the existing server-rendered `/admin` surface
(FastAPI + Jinja2) and sits entirely behind an authenticated admin/engineer
session. The production-line Pad app is not touched by this tool.

## Core concept: training = configuration, not fine-tuning

**"Training the digital inspector" does NOT fine-tune model weights.** The Qwen
VL weights are fixed. "Training" a SKU means configuring its **inspection
standard**:

- **standard photos** — reference images of a correct unit,
- **detection points** — the specific things to check,
- **pass/fail requirements** — the criteria per point.

The VL model consumes this configuration as inference *context*. The gate that
"graduates" a standard is **explicit human confirmation** — nothing becomes
active by AI extraction alone. In the UI this is surfaced directly:
**unconfirmed = inactive**.

A SKU is considered **trained** only when all three exist together:

1. at least one standard photo,
2. an **active** standard revision,
3. at least one active detection point on that revision.

This is the same status the production-line Pad task list relies on.

## Authentication

All pages require an admin/engineer session.

- `GET /admin/login` — sign-in page.
- `POST /admin/login` — authenticates a `QCOperatorProfile` whose `role` is
  `admin` or `engineer`; the operator's `tenant_id` becomes the authoritative
  tenant for every page. Passwords are checked with `hmac.compare_digest`.
- `POST /admin/logout` — clears the session.

Browser GET pages redirect to `/admin/login` when unauthenticated; mutations
return `401`. The tenant is always taken from the session, never from the
request.

## Flow 1 — Sample Intake (SKU registration)

Backed by the sample DB (`QCSkuItem`, `QCStandardPhoto`, `QCStandardIntake`).

| Page | Route |
|------|-------|
| SKU list + search (tenant-scoped) | `GET /admin/samples?q=<term>` |
| Create SKU | `GET /admin/samples/new`, `POST /admin/samples` |
| SKU detail (edit, photos, requirements, detection points) | `GET /admin/samples/{sku_id}` |
| Standard photos: upload / set primary | `POST /admin/samples/{sku_id}/photos`, `.../photos/{id}/set-primary` |
| Raw standard intake (paste requirement text) | `GET/POST /admin/samples/{sku_id}/intakes` |

Photo uploads use the hardened upload path (MIME whitelist `image/jpeg`,
`image/png`, `image/webp`; size cap via `MAX_UPLOAD_BYTES`, default 10 MB;
`sku_id` validated against `^[A-Za-z0-9_-]{1,128}$` before any filesystem use).

## Flow 2 — Digital Inspector Training

Backed by the intake pipeline (`src/intake/service.py`) and standard revisions
(`QCSkuStandardRevision`, `QCDetectionPoint`).

| Step | Route | What happens |
|------|-------|--------------|
| **Extract** | `POST /admin/intakes/{id}/extract` | AI extraction proposes candidate detection points from the raw text. Fail-closed: a provider/parse failure leaves the intake extractable with a visible error and never auto-confirms. |
| **Review & edit** | `GET /admin/intakes/{id}` | Engineer edits candidates side-by-side with the raw text — add / remove / rename, set severity, set pass/fail criteria. Empty rows are ignored. |
| **Confirm & activate** | `POST /admin/intakes/{id}/confirm` | Confirmation creates and activates a new standard revision and archives the prior one. Revision history (version, activated_at, active flag) is shown on the SKU intake page. |
| **Reject** | `POST /admin/intakes/{id}/reject` | Closes the intake without creating any revision. |

### Training status dashboard

`GET /admin/training` lists every tenant SKU with: has standard photos?
has active revision? detection-point count? last revision date? and a
**Trained / Not trained** badge computed by
`src.config_ui.service.compute_training_status`.

## Server-side extraction provider

On the server edition, extraction may use the configured cloud provider
(DashScope/Qwen) under the existing env gating (`LLM_ENABLE_REAL_CALLS`, etc.).
Existing fail-closed behavior is respected: a provider failure leaves the
intake in an extractable state with a visible error and never auto-confirms.

## Related modules

- `src/api/config_ui_router.py` — the training/intake pages.
- `src/api/sample_admin_router.py` — SKU list/create/detail, photos, login.
- `src/api/admin_auth.py` — session auth for `/admin`.
- `src/config_ui/service.py` — training-status read models.
- Templates: `training_dashboard.html`, `sku_intakes.html`,
  `intake_workbench.html`, `admin_login.html`.
