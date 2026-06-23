# Provider-Neutral Multimodal QC Architecture

This document describes the provider-neutral multimodal QC layer introduced in
`claude/multimodal-qc-provider-neutral-51e42r` (server) and `feat/pad-multimodel-sync`
(Pad). It is the architecture reference for both PRs.

---

## 1. Goals

- Decouple QC product logic from Qwen-specific APIs
- Support Qwen, OpenAI, Anthropic, local MNN, CV, and mock providers through one interface
- Share a single contract version string (`multimodal-qc-v1`) between server and Pad
- Enforce fail-closed policy at every layer (missing image / model error → `review_required`)
- Never call real APIs in unit tests; never commit API keys

---

## 2. Server Architecture (`src/multimodal/`)

```
src/multimodal/
  contract.py               ← QC_CONTRACT_VERSION, VALID_RESULTS, normalize_result()
  config.py                 ← env-var accessors (MULTIMODAL_PROVIDER, etc.)
  errors.py                 ← MultimodalConfigError, MultimodalProviderError, …
  types.py                  ← MultimodalRequest, MultimodalRawResponse, QCItemResult, …
  router.py                 ← CapabilityRouter (image quality → QC inspection → grounding)
  providers/
    base.py                 ← MultimodalProvider ABC
    registry.py             ← get_provider() — env-driven provider selection
    qwen_dashscope.py       ← QwenDashScopeProvider (transport-only, no QC logic)
    mock_provider.py        ← MockProvider (deterministic, no API calls)
    local_mnn_stub.py       ← LocalMnnProviderAdapter (review_required when not provisioned)
    local_server_adapter.py ← LocalServerAdapterProvider (wraps QwenQCService, no HTTP)
    cv_adapter.py           ← CvAdapterProvider (OpenCV SSIM, graceful degradation)
  parsers/
    validators.py           ← clamp_confidence, validate_bbox, reject_hallucinated_ids, …
  prompts/                  ← versioned prompt packs per capability
```

### 2.1 Provider Selection

| Env var | Default | Effect |
|---|---|---|
| `MULTIMODAL_PROVIDER` | `qwen` | Selects provider |
| `MULTIMODAL_ENABLE_REAL_CALLS` | `false` | `false` → always `MockProvider` |
| `QWEN_API_KEY` / `DASHSCOPE_API_KEY` | — | Required when provider=qwen and real calls enabled |
| `OPENAI_API_KEY` | — | Required when provider=openai and real calls enabled |
| `ANTHROPIC_API_KEY` | — | Required when provider=anthropic and real calls enabled |

Valid provider names: `qwen`, `openai`, `anthropic`, `local_mnn`, `local_server`, `cv`, `mock`.

### 2.2 Fail-Closed Rules

1. Missing image file → `review_required`
2. Image quality unusable → stop pipeline, return `review_required`
3. On-device `fail` is final (when `QC_CLOUD_CAN_OVERRIDE_LOCAL_FAIL=false`)
4. Hallucinated QC point IDs rejected; missing IDs filled as `review_required`
5. `validate_bbox` returns `None` for out-of-range coordinates
6. Provider raises → `review_required`, never re-raise as `pass`

---

## 3. Pad Architecture (`apps/android-qc/.../multimodal/`)

```
apps/android-qc/app/src/main/kotlin/com/giraffetechnology/qc/multimodal/
  SharedQcContract.kt          ← QC_CONTRACT_VERSION, VALID_RESULTS, normalizeResult()
  MultimodalInspector.kt       ← Provider-neutral interface (replaces QwenInspector at router)
  MultimodalInspectionRouter.kt← Router: mock → localMnn → backendProxy
  MultimodalProviderConfig.kt  ← Config data class with safe production defaults
  LocalMnnInspector.kt         ← Wraps MnnQwenInspector via MultimodalInspector
  BackendProxyInspector.kt     ← HTTP POST /api/v1/qc/inspect to server
  MockInspector.kt             ← Deterministic mock for CI
```

### 3.1 Provider Priority

1. `MockInspector` — `config.mockEnabled=true` (CI/test)
2. `LocalMnnInspector` — `config.localMnnEnabled=true` (default production)
3. `BackendProxyInspector` — `config.backendProxyEnabled=true` (opt-in)

### 3.2 Invariants

- `PAD_ALLOW_DIRECT_CLOUD` is always `false`; `MultimodalProviderConfig` enforces this in `init`
- On-device `fail` is final — no escalation to backend proxy
- All result values normalised through `SharedQcContract.normalizeResult()` before returning
- `BackendProxyInspector` sends `X-QC-Contract-Version` header on every request

---

## 4. Shared Contract

See `docs/contracts/multimodal_qc_contract_v1.md` for the full spec.

Version constant locations:
- Python: `src/multimodal/contract.py` → `QC_CONTRACT_VERSION = "multimodal-qc-v1"`
- Kotlin: `SharedQcContract.QC_CONTRACT_VERSION = "multimodal-qc-v1"`

Golden JSON fixtures: `tests/fixtures/contracts/`
Contract tests: `tests/test_multimodal_contract_schema.py` (run standalone, no model key)

---

## 5. Legacy Compatibility

`src/qwen/` and `src/llm/` are unchanged. The existing `POST /api/v1/qc/inspect`
endpoint continues to call `QwenQCService` directly. The multimodal layer is
an additive overlay — both paths are active until the router is wired to the
new `CapabilityRouter`.

On the Pad, the existing `QwenInspectionRouter` and `MnnQwenInspector` classes
are unchanged. `LocalMnnInspector` wraps `MnnQwenInspector` and delegates all
calls through to it. Existing tests targeting `QwenInspectionRouter` continue
to pass without modification.
