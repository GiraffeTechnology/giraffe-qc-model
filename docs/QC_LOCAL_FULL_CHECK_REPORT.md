# QC Local Full System Check — Report

**Scope:** local / simulated end-to-end verification of `main`. **No CTYUN, no
physical Pad, no real camera, no real MNN hardware inference, no production
external services** were used. Every Pad-side behaviour below is exercised
through the Pad's server-facing API (simulated), not a device.

---

## 1. Tested commit & environment

| | |
|---|---|
| Commit SHA | `ed770a4092f6d1a7e19f8ff7f41596c69ecdba0d` (branch `main`) |
| Python | 3.11.15 |
| Package manager | `uv` 0.8.17 (repo uses `uv.lock`) |
| OS | Linux 6.18.5 (x86_64, glibc 2.39) |
| Working tree | clean (no uncommitted changes before testing) |

Baseline confirmed present: #42 (S3/S4 migrations), #43 (Ed25519 `.tar.gz`
bundle), #45 (authoring extension: process card / region annotation /
probation), #40 (S7 E2E + delivery report).

---

## 2. Static repository integrity — PASS

- Backend: `src/api/*` (21 routers incl. `qc_studio_router`, `qc_bundle_router`,
  `qc_verdict_router`, `qc_qualification_router`, `pad_router`,
  `qc_source_router`), `src/qc_model/*` (bundle, studio, verdict, ingestion,
  providers, runtime_profiles).
- Admin UI: server-rendered Jinja templates under `src/web/templates` (no
  separate JS build); pages mounted by the routers above.
- Pad / Android: `apps/android-qc` (JVM/Kotlin unit-test harness; no device).
- Contracts: `contracts/openapi.yaml`, `contracts/schemas/`,
  `contracts/state_model.py`, `contracts/kotlin/`, `CONTRACTS.md`.
- Docs: `README.md`, `docs/QC_S7_DELIVERY_REPORT.md`,
  `docs/QC_STANDARD_AUTHORING_EXTENSION.md`, plus per-session docs.
- Live OpenAPI: `/openapi.json` → **195 paths**; `/docs` → 200.

---

## 3. Migration & database — PASS

Commands (fresh temp SQLite via `QC_DB_URL`):

```
alembic heads                 → 021 (head)   [single head]
alembic upgrade head          → 001 … → 021  clean
alembic downgrade 017         → clean
alembic upgrade head          → clean (re-upgrade)
```

- Chain is linear and single-headed: **017 → 018 → 019 → 020 → 021**.
- Key tables present after upgrade: `qc_sku_items`, `qc_detection_points`
  (incl. **`regions_json`**), `qc_publish_bundles`, `qc_bundles`,
  `qc_workstations`, `qc_bundle_assignments`, `qc_pad_submissions`,
  `qc_server_verdicts`, `qc_probations`, `qc_probation_jobs`.
- No migration collision / multiple heads.

---

## 4. Backend test suite — PASS

| Command | Result |
|---|---|
| `pytest` (full) | **1036 passed, 6 skipped** |
| `pytest tests/test_migrations.py tests/test_e2e_admin_to_pad.py` | 19 passed |
| `pytest -k "bundle or ed25519 or studio or probation or verdict or workstation or tenant"` | 177 passed |

**Skips (6) — all deliberate, not defects:** every skip is
`tests/integration/test_qwen_cloud_dev_real_call.py` gated behind
`RUN_QWEN_INTEGRATION=1` (calls the real DashScope cloud API — out of scope for
a local/simulated run). No failures; results deterministic across repeated runs.

---

## 5. Ed25519 bundle verification — PASS (fail-closed)

**Forbidden legacy patterns:** no `BUNDLE_SIGNING_SECRET`, no
`QC_BUNDLE_SIGNING_KEY` usage (only a docstring naming it as deprecated), no
bundle-signing `secret=`, no HMAC signing in `bundle/`, `studio/`, `sync/`.
Constant-time `hmac.compare_digest` remains only for SHA-256 checksum comparison
and for auth/device tokens — not bundle signing.

**Canonical env vars present:** server `QC_BUNDLE_SIGNING_PRIVATE_KEY_PEM` /
`_PATH`; verifier `QC_BUNDLE_VERIFY_PUBLIC_KEY_PEM` / `_PATH`.

**Live build + verify (in-process, and cross-process via a provisioned keypair):**

| Case | Result |
|---|---|
| valid archive, correct key | verify OK; **region metadata present inside signed manifest** |
| tampered manifest | rejected — invalid bundle signature |
| tampered photo payload | rejected — payload checksum mismatch |
| missing photo payload | rejected — missing payload files |
| tampered checksum | rejected — invalid bundle signature |
| tampered signature | rejected — invalid bundle signature |
| wrong public key | rejected — invalid bundle signature |
| no key outside test mode | `SigningKeyError` — fail-closed (no ephemeral fallback) |

Canonical layout confirmed on the downloaded bundle: `manifest.json`,
`checksum.sha256`, `bundle.sig`, `photos/…`.

---

## 6. Admin UI local run — PASS

Booted `uvicorn src.api.main:app` against a migrated SQLite DB with a
**provisioned Ed25519 keypair** (`QC_BUNDLE_SIGNING_PRIVATE_KEY_PATH` /
`QC_BUNDLE_VERIFY_PUBLIC_KEY_PATH`). Pages render (HTTP 200): `/`, `/admin`,
`/admin/studio`, `/admin/bundles`, `/admin/workstations`, `/admin/results`.

Admin flow driven live over HTTP (SKU `FLW-001`, tenant `tenant_acme`):
create SKU → upload standard photo (tenant-aware URL, 200) → describe
requirements ("pearl count 3, rhinestone count 8", center, petal defects) →
**4 detection points extracted** (`PEARL_COUNT`, `RHINESTONE_COUNT`,
`STAMEN_CENTERING`, `PETAL_INTEGRITY`) → confirm → `standard_active` → publish
**Ed25519** L2 bundle → download re-verified `.tar.gz`.

Count-less mentions trigger a follow-up rather than a guessed count (verified in
suite `test_admin_studio`). Region validation is fail-closed (see §9 finding).

---

## 7. Pad-simulated run — PASS (simulated)

> No physical Pad, no real camera, no CTYUN were used.

Via the Pad's server-facing API: record signed bundle in S3 (201) → register
workstation → assign bundle (`assigned_bundle_version=1.0.0`) → report installed
(`in_sync=true`) → submit inspection result. On-device MNN inference stays
fail-closed — `MnnRuntimeLoader.JNI_INFERENCE_WIRED=false` gates the Ready
transition, so the Pad reports "model pending" and no simulated run can pose as a
verified production inference.

---

## 8. Full local E2E scenario — PASS

Live HTTP, one tenant + `FLW-001` threaded Admin → Pad → Server:

```
STANDARD authored & active; 4 detection points
PUBLISH+DOWNLOAD: http 200 | client-verified Ed25519 OK | manifest/checksum/sig + photos/
S3 record bundle 201 | assign 1.0.0 | report in_sync True
S4 PASS recompute: server=pass, agrees=True
Admin Results page 200, "Server Verdict" shown
```

**Fail-closed matrix (live HTTP):**

| Case | Expected | Actual |
|---|---|---|
| a. PASS-over-fail checkpoint | server overrides to fail | `fail`, agrees `False` ✅ |
| b. PASS with missing checkpoint | non-pass | `review_required` ✅ |
| c. unknown standard revision | review-required | `review_required` ✅ |
| d. tampered bundle signature | rejected | HTTP 400 `invalid_signature` ✅ |
| e. cross-tenant photo access | rejected | owner 200 / wrong-tenant 404 / route-default 404 ✅ |
| f. non-image upload (MIME sniff) | rejected | HTTP 415 ✅ |

The safety-critical rule holds end to end: the server never lets a Pad-claimed
PASS stand over a failed/missing checkpoint, and it recomputes against the exact
revision the Pad cited — never the latest.

---

## 9. UI / product-requirement check — PASS with one non-blocking gap

- Language switch present on admin pages; i18n verified in suite; landscape-first
  Pad layout + conversation-first design covered by the Android JVM suite.
- Administrator / Operator separation present; Admin authoring, publish,
  workstation management, and probation/qualification surfaces exist.

**Non-blocking gap (P2):** detection-point **region annotation** (#45) is
implemented as a fail-closed service layer (`src/qc_model/studio/regions.py`:
coords in [0,1], `x+w≤1`/`y+h≤1`, positive area, `image_id` must belong to the
SKU, no extra keys — all rejections verified) and is surfaced in the studio
detection-point view and the signed publish manifest, **but there is no HTTP/UI
route to set or edit regions** — only the service function
`set_detection_point_regions` and unit tests exercise it. Regions are optional
(0..many), so the publish/Pad/verdict path is unaffected; this only limits
operator-driven region authoring from the UI.

---

## 10. Security / safety / isolation — PASS

- **Tenant isolation:** cross-tenant standard-photo access returns 404 (live);
  bundle/workstation/result routes are tenant-scoped (suite `-k tenant`, 177
  focused tests pass).
- **Auth guard:** `src/api/startup.py` `session_secret()` raises `RuntimeError`
  on an unset/dev-default secret outside `APP_ENV=test`; the test-only anonymous
  passthrough is impossible in production (`src/api/authz.py`).
- **Bundle safety:** signature verified before trust; checksum covers every
  payload; missing/smuggled payload and wrong key rejected (§5).
- **QC safety:** no confirmed standard → publish fails closed; counting
  checkpoints without a value are rejected; false-PASS paths fail closed (§8);
  provider L2 fails closed to `review_required` when unconfigured.
- **Auditability:** standard revisions, detection points, submissions, server
  verdicts, and probation jobs are all persisted as first-class rows.

---

## 11. Provider / model boundary — PASS

- Provider is configurable, not hardcoded (`src/qc_model/providers/qwen3_5_vl.py`,
  provider-neutral base).
- Runtime profiles (`src/qc_model/runtime_profiles.py`):
  `tablet_mnn → qwen3.5-vl-2b-mnn`, `server → qwen3.5-vl-8b-int4`.
- **No desktop-PC MNN runtime profile is registered as a default** anywhere
  (the repo's guardrail test forbids that profile token in `src/` and `docs/`).
- Provider failure / missing config → `review_required` / fail-closed; local
  test mode does not claim real visual accuracy; MNN inference remains scaffolded
  and fail-closed.

---

## 12. Documentation consistency — PASS with one stale-doc finding

- README / delivery report make **no** forbidden claims (no "physical Pad
  verified", no CTYUN deployment, no real-camera/MNN-hardware verification, no
  generic-SaaS positioning, no HMAC production signing).
- Honest scope (simulated / fail-closed / Ed25519 / limitations) is stated.

**Non-blocking finding (P3):** `docs/QC_S7_DELIVERY_REPORT.md` predates #42/#43/#45
and is now stale in three places:
- §6 says *"Publish produces an HMAC-signed L2 bundle"* — it is now **Ed25519**.
- §8 / §9 list *"Unified bundle format"* and *"DB migrations for S3/S4 tables"*
  as **not implemented / pending** — both were delivered (#43, #42).

This report supersedes those statements; correcting them in the S7 report is a
minor doc-only follow-up.

---

## 13. Known limitations

1. No physical Pad / camera / CTYUN / real MNN hardware — all Pad behaviour
   simulated via server-facing API and JVM unit tests.
2. On-device MNN inference not wired (`JNI_INFERENCE_WIRED=false`; "model pending").
3. Region annotation has no HTTP/UI edit route yet (§9, P2).
4. `docs/QC_S7_DELIVERY_REPORT.md` stale on bundle format + migrations (§12, P3).
5. Real Qwen cloud tests skipped unless `RUN_QWEN_INTEGRATION=1` (§4).

## 14. Blocking bugs

**None.**

## 15. Non-blocking issues

| Sev | Item | Path | Note |
|---|---|---|---|
| P2 | Region annotation has no HTTP/UI route | `src/qc_model/studio/regions.py` (service only) | Backend + validation + manifest + tests done; operator can't author regions from UI. |
| P3 | S7 delivery report stale (HMAC claim, migrations/bundle "pending") | `docs/QC_S7_DELIVERY_REPORT.md` | Correct §6/§8/§9 to reflect #42/#43. |

---

## 16. Final judgment

```
PASS — local simulated QC system runs end-to-end:
Admin UI → standard authoring → Ed25519 bundle publish → simulated Pad install/submit
→ server recompute → Admin result view.

No CTYUN test was performed.
No physical Pad test was performed.
No real camera test was performed.
Known limitations are documented above.
```
