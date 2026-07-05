# Session 7 — Integration, E2E, Security & Final Delivery Report

**Scope:** integration/E2E/security tests + acceptance sign-off across the
merged S1–S6 product (PRD §15, §16, §17, §19, §20). S7 runs last and adds no new
product features — it verifies that the independently-built sessions compose.

> **Hardware statement (read first).** No physical production-line Pad was used
> in this delivery. Every Pad-side behaviour below is **simulated** — exercised
> either as Android JVM unit tests (no device, no camera, no real MNN inference)
> or as the Pad's server-facing API calls. Nothing in this report is
> hardware-verified. On-device inference is deliberately **fail-closed**: the
> Pad claims at most *"MNN native ready; model pending"* until a real native
> inference path is wired (`MnnRuntimeLoader.JNI_INFERENCE_WIRED`), so no
> simulated run can masquerade as a verified production inference.

---

## 1. Merged product under test

`main` at S7 contains, in merge order:

| PR | Session | Surface |
|----|---------|---------|
| #34 | S1 | Web shell — welcome, `/admin` home, navigation, i18n |
| #35 | S3 | Bundle management + workstation management (`/admin/bundles`, `/admin/workstations`) |
| #36 | S5 | Android Pad shell — welcome, landscape, i18n, offline operator task selection |
| #37 | S4 | Server verdict recomputation + Admin Results (`/admin/results`) |
| #39 | S2 | Admin Studio — chat-first SKU + standard training + signed L2 bundle (`/admin/studio`) |
| #38 | S6 | Android Pad QC Work page + result submission |

Integration fixes applied while merging (all green on `main`):
- Tenant-aware Studio standard-photo URLs (Codex P2) — previews for non-default
  tenants no longer 404; tenant isolation stays fail-closed.
- Web-shell reconciliation — the S1 scaffold stubs for `/admin/studio`,
  `/admin/bundles`, `/admin/workstations`, `/admin/results` are removed now that
  S2/S3/S4 own the real pages, which carry the shared language switch.
- One S6 Android unit-test method name contained a `;` (illegal in a JVM/dex
  method name) and broke `:app:compilePadLocalDebugUnitTestKotlin`; renamed.

---

## 2. CI results

| Workflow | Job | Result |
|----------|-----|--------|
| `tests` | `python-tests` | ✅ pass |
| `QC Model Full Acceptance` | `Python + Pad API acceptance` | ✅ pass |
| `Android Pad CI` | `Build & Test (3x consecutive)` | ✅ pass (APK assembles; unit tests pass 3×) |

Local full Python suite at S7: **896 passed, 6 skipped**.
Android JVM unit tests: **173 `@Test` cases across 32 files** (run 3× consecutively in CI).

---

## 3. Definition-of-Done flow (§15) — Admin → Pad → Server

The single required demo is exercised as an automated integration test:
`tests/test_e2e_admin_to_pad.py::test_admin_to_pad_e2e_definition_of_done`.

One tenant (`tenant_acme`) and one SKU (`FLW-001`) are threaded through the
surfaces three separate sessions own, asserting the hand-off at each seam:

1. **S2 Studio** — create SKU `FLW-001` via chat → upload standard photo →
   describe requirements (`pearl count 3, rhinestone count 8`) → confirm →
   **active standard revision + detection points** → publish **signed L2 bundle**.
2. **S3 Bundle/Pad** — record a signed bundle → register a simulated workstation
   → assign the bundle → the Pad reports the installed version → **in-sync**.
3. **S4 Server** — the Pad submits its result carrying the exact
   `standard_revision_id` + `bundle_version` it ran → the server **recomputes**
   the authoritative verdict against that revision → Admin Results shows it.

The recompute reads the **same** `QCSkuStandardRevision` / `QCDetectionPoint`
rows the Studio confirmation wrote (`resolve_spec` in
`src/qc_model/verdict/service.py`), so this is a real data hand-off, not three
isolated fixtures.

---

## 4. Required test suites (§16)

| § | Suite | Where | Status |
|---|-------|-------|--------|
| 16.1 | Web/Admin | `test_admin_studio.py`, `test_web_shell.py`, `test_sample_admin.py`, `test_qc_bundle_management.py`, `test_qc_workstation_management.py`, `test_server_verdict_results_api.py` | ✅ verified |
| 16.2 | Android/Pad (layout, offline, readiness) | `apps/android-qc/.../src/test` (`PadReadinessTest`, `OperatorTaskSelectionControllerTest`, `ConversationBuilderTest`, `PreviewBoxCalculationsTest`, …) | ✅ verified (JVM unit, simulated) |
| 16.3 | Admin-to-Pad E2E (9-step chain) | `test_e2e_admin_to_pad.py` | ✅ verified |
| 16.4 | Security / fail-closed | see §5 below | ✅ verified |
| 16.5 | i18n | `test_web_shell.py` (device default, English fallback, persistence, every admin page carries `lang-switch` + 🌐), `PadLanguageSkillTest`, `LanguageResolverTest` | ✅ verified |

---

## 5. Security / fail-closed (§16.4)

| Guarantee | Test | Status |
|-----------|------|--------|
| Oversize upload rejected (413) | `test_admin_studio::test_upload_rejects_oversize` | ✅ |
| Non-image rejected by MIME sniff (415) | `test_e2e_admin_to_pad::test_e2e_studio_upload_rejects_non_image`, `test_admin_studio::test_upload_rejects_non_image` | ✅ |
| Missing bundle signature rejected | `test_qc_bundle_management::test_verify_bundle_rejects_missing_signature` | ✅ |
| Tampered bundle rejected on ingest | `test_e2e_admin_to_pad::test_e2e_tampered_bundle_signature_rejected` | ✅ |
| PASS-with-failed-checkpoint → server `fail` | `test_e2e_admin_to_pad::test_e2e_pad_claimed_pass_is_overridden_on_failed_checkpoint` | ✅ |
| PASS-with-missing-checkpoint → non-pass | `test_e2e_admin_to_pad::test_e2e_pad_claimed_pass_with_missing_checkpoint_is_not_pass` | ✅ |
| Unknown revision → `review_required` (fail closed) | `test_e2e_admin_to_pad::test_e2e_unknown_revision_fails_closed` | ✅ |
| Tenant isolation on Studio photos | `test_e2e_admin_to_pad::test_e2e_studio_photo_isolated_across_tenants` | ✅ |

The safety-critical rule holds end to end: **the server never lets a
Pad-claimed PASS stand** over a failed or missing checkpoint, and it evaluates
against the exact revision the Pad used — never the latest.

---

## 6. Acceptance criteria (§17) — sign-off

**Must Pass**
- ✅ Chat can create a SKU; upload is validated and previewable (tenant-aware).
- ✅ Missing counts trigger a follow-up; counts are never guessed.
- ✅ Confirmation persists `method_hint` / `expected_value` / `pass_criteria`.
- ✅ Publish produces an HMAC-signed L2 bundle; fails closed with no confirmed standard.
- ✅ Bundle history/download; register + assign a (simulated) workstation.
- ✅ Offline operator SKU selection returns installed standards with no backend call.
- ✅ Server recomputes the verdict against the used revision; shown in Admin Results.
- ✅ Every admin page carries the language switch; device/fallback/persistence work.

**Must Not Happen**
- ✅ A Pad-claimed PASS is never accepted over a failed/missing checkpoint.
- ✅ A tampered/unsigned bundle is never served or installed.
- ✅ One tenant cannot read another tenant's standard photos by guessing IDs.
- ✅ The Pad never claims full production readiness the native path has not earned.

---

## 7. Proof index

- **CI results:** §2.
- **Admin-to-Pad E2E proof:** `tests/test_e2e_admin_to_pad.py` (§3).
- **Language switching proof:** `test_web_shell.py::test_every_admin_page_has_language_switch`, `PadLanguageSkillTest` (§4, §16.5).
- **Offline Pad SKU selection proof:** `OperatorTaskSelectionControllerTest` — empty-store, offline search, not-found, confirm-builds-`QcTask`, all local-only (simulated).
- **Server recomputed verdict proof:** `test_server_verdict_recompute.py` (11 pure-core cases) + the E2E fail-closed cases (§5).
- **Screens:** the six key surfaces (Welcome, Admin home, Studio, Bundles/Workstations, Results, Pad QC Work) render in the suites above; visual capture requires a running server / Android device and is **not** attached here.

---

## 8. Delivery status (§19) — honest separation

### Implemented and verified (automated, no hardware)
- S1 web shell, i18n, navigation.
- S2 Admin Studio: chat SKU creation, hardened upload, NL requirement extraction,
  count follow-ups, confirmation, signed L2 publish, tenant-aware previews.
- S3 bundle + workstation management with fail-closed signature verification.
- S4 server verdict recompute + Admin Results.
- Admin→Pad→Server E2E chain and the §16.4 fail-closed guarantees.

### Implemented but simulated (no physical Pad / no real inference)
- S5/S6 Android Pad shell, QC Work page, conversation, readiness, offline SKU
  selection, outbox/result submission — verified as **JVM unit tests**. No
  camera, no on-device MNN inference, no real factory-LAN device.
- The "Pad" in the E2E is its **server-facing API** (upload, workstation report,
  result submission), not a device.
- MNN on-device inference is **not wired** (`JNI_INFERENCE_WIRED = false`); the
  Pad reports *model pending* by design.

### Not implemented / pending
- **Unified bundle format.** S2 publishes a `studio-bundle-v1` HMAC manifest;
  S3 verifies a separate `manifest_version: 1` format (and PR #32 defines an
  Ed25519 `.tar.gz` envelope). These are **not yet reconciled** — the E2E
  records the S3-format bundle rather than feeding the S2 studio bundle straight
  into S3. Single source of truth is pending S0 reconciliation.
- **DB migrations for S3/S4 tables.** `qc_bundles`, `qc_workstations`,
  `qc_bundle_assignments`, `qc_pad_submissions`, `qc_server_verdicts` are created
  via `Base.metadata.create_all` and have **no Alembic migration**. Tests are
  unaffected; a production `alembic upgrade` would not create them yet.
- **On-device MNN inference** and **real hardware Pad run** — pending device.
- **Studio voice input** — returns a controlled "not enabled" response.

---

## 9. Known limitations (summary)

1. No physical Pad tested — all Pad behaviour simulated (JVM unit / API).
2. On-device MNN inference not wired; Pad is fail-closed to "model pending".
3. Two bundle-manifest formats (studio vs S3/offline-sync) not yet unified.
4. S3/S4 tables lack Alembic migrations (create_all only).
5. Voice input is a controlled stub.

---

## 10. Completion statement (§20)

S1–S6 are merged and green on `main`. The Admin → Pad → Server Definition-of-Done
flow is verified as an automated integration test, and the safety-critical
fail-closed guarantees hold end to end. All Pad-side behaviour is **simulated**,
never hardware-verified, and on-device inference remains fail-closed. The items
in §8 "Not implemented / pending" — chiefly the unified bundle format, S3/S4
migrations, and a real device run — are the remaining work before a production
hardware pilot.
