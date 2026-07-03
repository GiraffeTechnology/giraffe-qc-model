# VERIFICATION — Task 02: Backend P0 Security Fixes + Configuration Web UI

Raw command output with a binary PASS/FAIL per acceptance item. All API calls
below were run against a live `uvicorn src.api.main:app` started in a
non-test environment (`APP_ENV=production`) with a strong `SESSION_SECRET`
and `API_TOKEN_SECRET`.

Server env for the curl evidence:

```
APP_ENV=production
SESSION_SECRET=verify-strong-session-secret-1234567890
API_TOKEN_SECRET=verify-strong-api-token-secret-1234567890
QC_DB_URL=sqlite:///./verify.db
QC_SEED_DEMO_OPERATORS=true      # demo admin only, to exercise /admin login
MAX_UPLOAD_BYTES=4096            # small cap so oversize is easy to show
```

Tokens are minted with `src.api.auth.mint_token(<tenant>)` using the same
`API_TOKEN_SECRET`.

---

## 1. Full Python suite green (incl. new auth/authz + upload-hardening tests) — **PASS**

```
$ uv run pytest -q
...
857 passed, 6 skipped, 1 warning in 46.85s
```

New test files added by this task:
- `tests/test_api_authz.py` — anonymous 401 / cross-tenant 404 / correct-token 200 for every router group.
- `tests/test_upload_hardening.py` — size / MIME / traversal rejections (unit + end-to-end).
- `tests/test_startup_config.py` — SESSION_SECRET enforcement, seed gating, `hmac.compare_digest`.
- `tests/test_config_ui.py` — full training walkthrough → SKU "trained".

Baseline before this task was `807 passed, 6 skipped`; the 50 additional passes are the new tests. No prior test was deleted or weakened.

---

## 2. 401 on anonymous calls to every previously-open router group — **PASS**

```
--- qc_router: POST /api/v1/qc/standards (anon) ---
HTTP 401
--- sku_router: GET /api/v1/sku/search (anon) ---
HTTP 401
--- qc_intake_router: POST /api/v1/qc/intakes (anon) ---
HTTP 401
--- qc_inspection_router: POST /api/v1/qc/inspection-jobs (anon) ---
HTTP 401
--- sample_admin_router: POST /admin/samples (anon) ---
HTTP 401
--- sample_admin_router: GET /admin/samples (anon) → redirect to login ---
HTTP 303 -> http://127.0.0.1:8099/admin/login
```

The four JSON router groups return `401`. The `/admin` HTML surface returns
`401` on mutations and a `303` redirect to `/admin/login` on browseable GET
pages (the correct pattern for a browser tool) — it is no longer open.

---

## 3. Cross-tenant denial with a valid-but-wrong-tenant credential — **PASS**

```
tenant_a create: {"id":"f05fba4aa8524d69bd4bbf348def7de9","tenant_id":"tenant_a",...}
--- tenant_a (correct) GET → expect 200 ---
HTTP 200
--- tenant_b (wrong tenant) GET tenant_a's SKU → expect 404 ---
{"detail":"SKU not found"}
HTTP 404
--- tenant_a token, body claims tenant_b → expect 403 ---
{"detail":"tenant_id does not match authenticated principal"}
HTTP 403
```

Tenant is derived from the authenticated principal, not the request. A valid
token for `tenant_b` cannot read `tenant_a`'s resource (404, no existence
leak), and a request body attempting to claim a different tenant is rejected
(403).

---

## 4. Startup fails with unset/default SESSION_SECRET outside test env — **PASS**

Direct validation call:

```
$ env -u SESSION_SECRET APP_ENV=production uv run python -c \
    "from src.api.startup import validate_startup_config; validate_startup_config()"
RuntimeError: SESSION_SECRET must be set to a strong, non-default value before
starting outside the test environment. Refusing to start with an unset or
dev-default session secret (got <unset>).

$ APP_ENV=production SESSION_SECRET=dev-secret-change-in-prod uv run python -c \
    "from src.api.startup import validate_startup_config; validate_startup_config()"
RuntimeError: SESSION_SECRET must be set to a strong, non-default value ... (got de****od).
```

Real `uvicorn` boot with unset `SESSION_SECRET`:

```
$ env -u SESSION_SECRET APP_ENV=production uvicorn src.api.main:app --port 8100
RuntimeError: SESSION_SECRET must be set to a strong, non-default value before
starting outside the test environment. Refusing to start with an unset or
dev-default session secret (got <unset>).
ERROR:    Application startup failed. Exiting.
```

With a strong secret, `validate_startup_config()` passes and the app boots
(`{"status":"ok"}` on `/health`). Demo-operator seeding is also disabled
outside test unless `QC_SEED_DEMO_OPERATORS=true` (see
`tests/test_startup_config.py::TestSeedGating`).

---

## 5. Upload rejections (size / MIME / traversal) — **PASS**

```
--- valid PNG (baseline) → expect 200/303 ---
HTTP 303
--- wrong MIME (PDF/text) → expect 415 ---
{"detail":"Unsupported media type: only image/jpeg, image/png, image/webp are allowed"}
HTTP 415
--- oversized (>4096 bytes) → expect 413 ---
{"detail":"File too large: 5008 bytes exceeds limit of 4096 bytes"}
HTTP 413
--- traversal sku_id 'bad..id' reaches handler → expect 400 ---
{"detail":"Invalid sku_id: must match ^[A-Za-z0-9_-]{1,128}$"}
HTTP 400
--- traversal sku_id '..%2f..%2fetc' via URL → 404 (never reaches filesystem) ---
{"detail":"Not Found"}
HTTP 404
```

MIME is validated by content sniffing (a spoofed `Content-Type` cannot smuggle
a non-image), size is capped (default 10 MB, `MAX_UPLOAD_BYTES` configurable),
and `sku_id` is validated against a strict pattern before any filesystem use.
The same hardening applies to `POST /api/v1/pad/upload`
(`tests/test_upload_hardening.py::TestPadUpload`).

---

## 6. UI walkthrough: create SKU → photo → intake → extract → edit → confirm → trained — **PASS**

Live admin session (`/admin/login`, tenant `demo`, role `admin`):

```
1. create SKU TRAIN-9 : HTTP 303
2. upload photo      : HTTP 303
3. submit raw intake : HTTP 303
4. extract candidates: HTTP 303
5. confirm+activate  : HTTP 303
6. training dashboard status for TRAIN-9:
    TRAIN-9 Trainee 9 ✓ 1 v1 ✓ 1 2026-07-03 Trained
```

The rendered `/admin/training` row shows: standard photos ✓ (1), active
revision v1, detection points ✓ (1), and status **Trained**. The same flow is
asserted programmatically in `tests/test_config_ui.py::test_full_training_flow_marks_sku_trained`,
and `test_unconfirmed_intake_does_not_activate` confirms an unconfirmed intake
never activates (no-guess principle: unconfirmed = inactive).

---

## 7. No regression to inspection-job execution APIs — **PASS**

The existing execution-API test suites are green under the new auth layer:

```
$ uv run pytest -q tests/test_qc_intake_execution_api.py tests/test_qc_api.py \
      tests/test_multi_tenant.py
... all passed (included in the 857 total above)
```

Existing functional tests authenticate via a test-only dependency override
(`tests/_auth_override.py`) that preserves the pre-auth tenant semantics, so
business-logic coverage is unchanged; the genuine auth behavior is covered by
the dedicated `tests/test_api_authz.py`.

---

## Summary

| # | Acceptance item | Result |
|---|-----------------|--------|
| 1 | Full suite green incl. new tests | **PASS** |
| 2 | 401 on anonymous per router group | **PASS** |
| 3 | Cross-tenant denial | **PASS** |
| 4 | Startup fails on unset/default SESSION_SECRET | **PASS** |
| 5 | Upload rejections (size/MIME/traversal) | **PASS** |
| 6 | UI walkthrough → trained | **PASS** |
| 7 | No regression to execution APIs | **PASS** |
