# Foundation Contracts (Session 0)

**Status:** BLOCKING for S1–S6. Fixed once, in writing, before any UI code lands.

This is the single source of truth for the API/service seams in PRD §14 and the
supporting field/message/state shapes (§5.4, §6, §7, §9, §10, §11). Every
downstream session (S1–S6) references this file by name in its PR description and
imports the typed companion files rather than re-deriving shapes. **No UI, no
business logic lives here — contracts only.**

## Files in this folder

| File | Contract | PRD |
|------|----------|-----|
| [`CONTRACTS.md`](./CONTRACTS.md) | This index + narrative | — |
| [`openapi.yaml`](./openapi.yaml) | API contract for the five route groups | §14 |
| [`schemas/detection_point.schema.json`](./schemas/detection_point.schema.json) | Detection point (the §5.4 field set) | §5.4 |
| [`schemas/bundle_manifest.schema.json`](./schemas/bundle_manifest.schema.json) | Signed bundle manifest, fail-closed | §7 |
| [`schemas/verdict_recompute.schema.json`](./schemas/verdict_recompute.schema.json) | Server verdict recompute request/response | §9 |
| [`state_model.py`](./state_model.py) | Standard lifecycle states (Python) | §10 |
| [`kotlin/StandardState.kt`](./kotlin/StandardState.kt) | Same states (Kotlin mirror) | §10 |
| [`kotlin/SqliteStandardStore.kt`](./kotlin/SqliteStandardStore.kt) | Android on-device store interface | §14 |
| [`kotlin/GiraffeLanguageSkill.kt`](./kotlin/GiraffeLanguageSkill.kt) | i18n adapter (Kotlin) | §11 |
| [`i18n/i18n_contract.md`](./i18n/i18n_contract.md) | i18n adapter seam (both stacks) | §11 |
| [`i18n/en.json`](./i18n/en.json) | Canonical English source strings | §11 |

The JSON Schemas are authoritative for object shape. `openapi.yaml` inlines
mirrors of `DetectionPoint` and `StandardState` for tooling self-containment;
when they ever disagree, the standalone JSON Schema / enum file wins.

---

## 1. API contract — five route groups (§14)

Full spec: [`openapi.yaml`](./openapi.yaml). All routes mount under `/api/v1`,
require the `X-Tenant-ID` header, and return **404** on cross-tenant access
(existing repo convention, see `docs/API_CONTRACT.md`).

**Group 1 — Admin Studio** (`/admin/studio/*`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/admin/studio/messages` | Append an operator message to a draft's authoring thread |
| POST | `/admin/studio/upload-standard-photo` | Attach a standard reference photo (multipart) |
| POST | `/admin/studio/confirm-standard` | `ready_for_review → confirmed` |
| POST | `/admin/studio/reject-standard` | Send back → `needs_information` |
| POST | `/admin/studio/publish` | `confirmed → published` |

**Group 2 — Bundles** (`/bundles/*`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/bundles/export` | Build + sign a bundle from published SKUs |
| GET | `/bundles/history` | Paged list of past bundles |
| GET | `/bundles/{id}/download` | Download the signed archive |
| POST | `/bundles/{id}/assign-workstation` | Assign a bundle to a workstation |

**Group 3 — Workstations** (`/admin/workstations*`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/workstations` | List |
| POST | `/admin/workstations` | Register |
| GET | `/admin/workstations/{id}` | Get |
| PATCH | `/admin/workstations/{id}` | Update |
| DELETE | `/admin/workstations/{id}` | Retire |

**Every response that carries detection points embeds the `DetectionPoint`
object verbatim** — `DraftStandard`, `StandardRevision`, and the bundled SKU
entries all reference the same component. See §2 below.

---

## 2. Detection point — the §5.4 field set

Authoritative: [`schemas/detection_point.schema.json`](./schemas/detection_point.schema.json).
Exactly these ten fields, carried verbatim through the API, the bundle manifest,
and the on-device store. (The existing intake API in
`docs/QC_INTAKE_EXECUTION_API.md` already uses the first seven; this contract
adds and types the final three: `required_view`, `evidence_required`,
`incidental_finding_policy`.)

| Field | Type | Notes |
|-------|------|-------|
| `point_code` | string `^[A-Za-z][A-Za-z0-9_-]*$` | Stable id, unique within a revision. Accepts UPPER_SNAKE (`PEARL_COUNT`), hyphenated (`DP-FLOWER-FRONT-001`), and lowercase (`dp-bracelet-001`) |
| `label` | string | Short display name |
| `description` | string \| null | Fuller explanation; may be omitted |
| `method_hint` | string \| null | How to inspect; may be omitted |
| `expected_value` | string \| null | e.g. `"3"`; null when N/A |
| `pass_criteria` | string \| null | Explicit pass condition; may be omitted when implicit |
| `severity` | enum | `minor` \| `major` \| `critical` |
| `required_view` | enum | `front, back, left_side, right_side, top, bottom, interior, detail, any` |
| `evidence_required` | boolean | If true, a result needs an evidence image |
| `incidental_finding_policy` | enum | `flag_for_review` (default) \| `record_only` \| `ignore` |

`incidental_finding_policy` semantics: `flag_for_review` escalates the item to
`review_required`; `record_only` logs the finding without changing the verdict;
`ignore` drops it.

**Required vs. present.** The schema requires only the six fields that must
always have a concrete value (`point_code`, `label`, `severity`,
`required_view`, `evidence_required`, `incidental_finding_policy`); the four
free-text criteria fields are nullable and may be omitted, so existing
detection points that never captured them still validate. To satisfy §5.4
("carry all fields verbatim"), **API responses SHOULD still emit all ten keys**,
using `null` where a value was never authored — do not silently drop keys on the
wire.

---

## 3. State model (§10)

Authoritative: [`state_model.py`](./state_model.py) (Python) and its byte-for-byte
Kotlin mirror [`kotlin/StandardState.kt`](./kotlin/StandardState.kt). The **wire
value** is the only serialized form; display labels come from the i18n seam
(`state.<wire>` keys).

| Wire value | Display (en) |
|------------|--------------|
| `draft` | Draft |
| `needs_information` | Needs Information |
| `ready_for_review` | Ready for Review |
| `confirmed` | Confirmed |
| `published` | Published |
| `installed_on_pad` | Installed on Pad |
| `probation` | Probation |
| `active_inspection` | Active Inspection |
| `needs_requalification` | Needs Requalification |

Allowed transitions are enumerated in both files (`ALLOWED_TRANSITIONS` /
`allowedTransitions`) and enforced fail-closed — any pair not listed is rejected.
Authoring (Web) drives up to `published`; `installed_on_pad` onward is reported
by the Pad. A newly installed standard enters `probation` — mandatory human
confirmation on every real job — and only graduates to solo `active_inspection`
once the qualification gate is met (≥30 jobs, ≥90% AI/human agreement; PRD
Authoring Extension §3). `needs_requalification` loops back into authoring (§9).

---

## 4. Bundle manifest (§7)

Authoritative: [`schemas/bundle_manifest.schema.json`](./schemas/bundle_manifest.schema.json).
A signed bundle packages published SKU revisions plus reference photos:
`manifest_version`, `bundle_id`, `bundle_version`, `tenant_id`, `skus[]`,
`checksums` (SHA-256 over the manifest body and every photo), and a `signature`
block (`algorithm`, `key_id`, `signed_digest`, `value`).

**Fail-closed (§7):**
- `additionalProperties: false` at every level — there is **no**
  skip-verification flag, and one cannot be smuggled in.
- The Pad MUST verify the signature against a trusted `key_id` and every
  checksum before install; any mismatch aborts the install.
- Bundled SKU `state` is constrained to `published`.

---

## 5. Android local store (§14 — Pad Local Standards)

Authoritative: [`kotlin/SqliteStandardStore.kt`](./kotlin/SqliteStandardStore.kt).
S5/S6 implement this against SQLite; it is the only surface the Pad reads
installed standards through. All lookups are strictly offline and miss to
`null`/empty (never throw) so callers fail closed.

```kotlin
interface SqliteStandardStore {
    suspend fun searchInstalledSku(query: String): List<InstalledSku>
    suspend fun getInstalledSku(skuId: String): InstalledSku?
    suspend fun getInstalledStandardRevision(skuId: String): InstalledStandardRevision?
}
```

`InstalledStandardRevision` carries the full `DetectionPoint` set (§5.4) plus
bundle provenance, so an installed revision is self-sufficient for on-device
inspection with no server round-trip. This is the same three-method shape named
in PRD §14; it is new (no PR30 equivalent exists — PR30 ships `SkuRepository`,
a *network-backed* SKU lookup, which this deliberately supersedes for the
offline path).

The i18n adapter for the Pad is also here:
[`kotlin/GiraffeLanguageSkill.kt`](./kotlin/GiraffeLanguageSkill.kt) — see §6.

---

## 6. i18n seam (§11)

Authoritative: [`i18n/i18n_contract.md`](./i18n/i18n_contract.md) +
[`i18n/en.json`](./i18n/en.json). Both Web and Android bind text to one adapter
(`GiraffeLanguageSkill` / `LanguageSkill` protocol) with a `t(key, params)`
lookup, fail-soft on a missing key. `en.json` holds the canonical English source
strings for every screen in §11 (studio, bundles, workstations, pad) plus shared
enum labels; other locales mirror the same key set.

---

## 7. Verdict recompute (§9)

Authoritative: [`schemas/verdict_recompute.schema.json`](./schemas/verdict_recompute.schema.json).

**Request:** `tenant_id`, `sku_id`, `standard_revision_id`, `bundle_version`,
`submitted_verdict`, `checkpoint_results[]` (+ optional `incidental_findings[]`).

**Response:** `recomputed_verdict`, `submitted_verdict`, `agrees`,
`standard_revision_id`, `bundle_version`, and a structured `diff`
(`verdict_changed`, `false_pass_suspected`, `checkpoint_diffs[]`,
`unknown_point_codes[]`, `missing_point_codes[]`).

The server recomputes independently against the same revision and reports
disagreement. `false_pass_suspected` fires when the Pad submitted `pass` but the
server recomputed `fail`/`review_required` (§9 false-pass trigger, feeding
`needs_requalification`). Fail-closed: unknown or missing point codes force
`review_required`.

---

## Acceptance mapping

Every field named in the PRD sections below has a concrete type in this folder:

| PRD | Where |
|-----|-------|
| §5.4 detection-point fields | `schemas/detection_point.schema.json` (+ inline `DetectionPoint` in `openapi.yaml`, Kotlin `DetectionPoint`) |
| §6 response shapes carrying detection points | `openapi.yaml` (`DraftStandard`, `StandardRevision`, bundled SKU entries) |
| §7 signed bundle, fail-closed | `schemas/bundle_manifest.schema.json` |
| §9 verdict recompute | `schemas/verdict_recompute.schema.json` |
| §10 lifecycle states | `state_model.py` + `kotlin/StandardState.kt` |
| §11 i18n seam + English keys | `i18n/i18n_contract.md` + `i18n/en.json` + `kotlin/GiraffeLanguageSkill.kt` |
| §14 five route groups | `openapi.yaml` |
| §14 Pad local store | `kotlin/SqliteStandardStore.kt` |

S1–S6 can be started by different sessions against these contracts without
further clarification.
