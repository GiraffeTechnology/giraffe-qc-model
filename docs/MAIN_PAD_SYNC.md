# Main Server ↔ Android Pad Sync Guide

This document describes how `main` (server) and `android-pad-app` (Pad) are kept
synchronised around the provider-neutral multimodal QC contract.

---

## 1. Two Authoritative Branches

| Branch | Purpose | PR target |
|---|---|---|
| `main` | Python FastAPI server, provider registry, contract docs | `main` |
| `android-pad-app` | Android Kotlin Pad app, on-device MNN, backend proxy | `android-pad-app` |

Neither branch merges into the other. They share one contract version string and
one set of golden JSON fixtures.

---

## 2. The Shared Contract

**Contract version:** `multimodal-qc-v1`

The contract is the single source of truth for request/response field names,
canonical result values, and fail-closed policy. It lives in:

- `docs/contracts/multimodal_qc_contract_v1.md` (human-readable spec)
- `docs/contracts/multimodal_qc_result_schema_v1.json` (JSON Schema)
- `tests/fixtures/contracts/` (golden JSON fixtures, committed on `main`)

The Pad reads the same fixtures via `BackendProxyInspector` response parsing
and its own `ContractParsingTest.kt`.

---

## 3. Sync Rules

### 3.1 Adding a result field

1. Update `docs/contracts/multimodal_qc_contract_v1.md` on `main`
2. Update `multimodal_qc_result_schema_v1.json` on `main`
3. Update the golden fixtures on `main`
4. Update `BackendProxyInspector.parseServerResponse()` on `android-pad-app`
5. Update `ContractParsingTest.kt` on `android-pad-app`
6. Run `tests/test_multimodal_contract_schema.py` (server) and `ContractParsingTest` (Pad)

### 3.2 Bumping the contract version

1. Choose the next version string (e.g. `multimodal-qc-v2`)
2. Update `QC_CONTRACT_VERSION` in `src/multimodal/contract.py` (server)
3. Update `SharedQcContract.QC_CONTRACT_VERSION` in Kotlin (Pad)
4. Create new contract docs (`multimodal_qc_contract_v2.md`, new schema file)
5. Add new golden fixtures for v2
6. Update `BackendProxyInspector` to send the new version header
7. Coordinate both PR merges — a version mismatch between server and Pad
   causes `BackendProxyInspector` to log a version mismatch warning

### 3.3 Adding a provider (server only)

1. Create `src/multimodal/providers/<name>.py` implementing `MultimodalProvider`
2. Register in `src/multimodal/providers/registry.py`
3. Add `MULTIMODAL_PROVIDER=<name>` to `.env.example`
4. Add a unit test in `tests/test_multimodal_provider_registry.py`
5. No Pad change required (the Pad calls the server, not the provider directly)

### 3.4 Adding a Pad inspector

1. Implement `MultimodalInspector` in `apps/android-qc/.../multimodal/`
2. Wire into `MultimodalInspectionRouter` with a config flag
3. Add a test in `apps/android-qc/.../multimodal/*Test.kt`
4. No server change required unless the inspector calls a new server endpoint

---

## 4. PR Merge Order

For the initial rollout:

1. **PR: `claude/multimodal-qc-provider-neutral-51e42r` → `main`**
   Adds `src/multimodal/` base layer (types, providers, router, parsers).

2. **PR: `feat/server-multimodel-sync` → `main`**
   Adds contract docs, `src/multimodal/contract.py`, adapter stubs, golden fixtures.
   Depends on step 1.

3. **PR: `feat/pad-multimodel-sync` → `android-pad-app`**
   Adds Kotlin multimodal layer. Can merge independently of steps 1–2
   (Pad tests are standalone JVM unit tests).

---

## 5. Testing

| Suite | Command | Notes |
|---|---|---|
| Contract schema (server) | `make test` or `uv run pytest tests/test_multimodal_contract_schema.py -v` | No model key needed |
| Full server tests | `make test` | Requires `MULTIMODAL_ENABLE_REAL_CALLS=false` (default) |
| Live server integration | `make test-multimodal` | Requires `QWEN_API_KEY` and `MULTIMODAL_ENABLE_REAL_CALLS=true` |
| Pad unit tests | `./gradlew :app:test` from `apps/android-qc/` | JVM only, no device needed |
| Pad device tests | `./gradlew :app:connectedAndroidTest` | Requires connected device or emulator |
