# Test Report — giraffe-qc-model v3

## Summary

| Category | Count | Status |
|----------|-------|--------|
| Unit tests | 203 | ✅ All pass |
| Integration tests (opt-in) | 6 | ⏭ Skipped by default (expected) |
| Android/MNN physical-device tests | — | ⏳ Pending device |

Last full run: `uv sync --group dev && uv run pytest tests/ -v`
Consecutive passing runs: **5 / 5**

---

## 1. Unit Tests

**203 passed, 0 failed** — run via `uv run pytest tests/ -v`

| Test file | Tests | Notes |
|-----------|-------|-------|
| `test_cloud_qwen_dev_provider.py` | 16 | QC_ENGINE_MODE, key masking, guard checks |
| `test_cv_comparator.py` | 19 | Classical CV comparator |
| `test_db_schema.py` | 5 | DB schema + FK constraints |
| `test_llm_layer.py` | 10 | LLM provider abstraction |
| `test_multi_tenant.py` | 11 | Cross-tenant isolation (returns 404, not 403) |
| `test_qc_api.py` | 12 | FastAPI endpoints |
| `test_qc_comparison.py` | 5 | QC comparison orchestration |
| `test_qc_storage.py` | 11 | Photo storage, SHA-256, sidecar JSON |
| `test_qwen_parser.py` | 19 | JSON parser, hallucination rejection, fail-closed |
| `test_qwen_prompt_builder.py` | 24 | Prompt builder, version embedding, ROI/rule_type |
| `test_qwen_router.py` | 9 | Router core |
| `test_qwen_router_phase9.py` | 34 | §4.5.1–4.5.4 exhaustive branch coverage |
| `test_sample_store.py` | 8 | Sample store CRUD |
| `test_video_pipeline.py` | 15 | Video pipeline including stuck-in-running fix |

---

## 2. Integration Tests (opt-in, skipped by default)

**6 skipped** — `tests/integration/test_qwen_cloud_dev_real_call.py`

These tests make real DashScope API calls and are gated behind environment variables.
**Skipped integration tests are expected and correct in normal CI.**

To run them, all of the following must be set:

```bash
RUN_QWEN_INTEGRATION=1
QC_ENGINE_MODE=cloud_qwen_dev
LLM_ENABLE_REAL_CALLS=true
QWEN_CLOUD_ENABLED=true
ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true
DASHSCOPE_API_KEY=<real key>   # or QWEN_API_KEY
```

See `docs/V3_ON_DEVICE_QWEN_QC_PRODUCT.md` for full instructions.

---

## 3. Android / MNN Physical-Device Tests

Not yet run. Pending availability of a physical Snapdragon test device.

Planned tests are documented in `docs/MNN_DEVICE_TEST_PLAN.md`:
- Model provisioning (download + SHA-256 verify)
- Cold-start and per-image latency benchmark (target: ≤10 s, p95)
- JNI `nativeRunInference()` round-trip
- End-to-end offline inspection (capture → on-device → result)
- §4.5.4 `on_device_fail_is_final=true` verified on device
- Router cloud-fallback path with device present

---

## Fixed

- **`uv sync` removes test tooling**: fixed by adding `[dependency-groups]` dev
  section to `pyproject.toml`. `uv sync --group dev` (or `make sync-dev`)
  now reliably installs pytest before tests.

---

## Non-blocking

- **httpx/starlette deprecation warning**: pre-existing; `StarletteDeprecationWarning:
  Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
  No test failures. Track separately and update when httpx2 is stable.

---

## Expected skips

Qwen real API integration tests are skipped unless:
- `RUN_QWEN_INTEGRATION=1`
- `DASHSCOPE_API_KEY` or `QWEN_API_KEY` is present
- `QWEN_CLOUD_ENABLED=true`
- `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true`

This is intentional. CI must never make real API calls or require a secret
to pass. The 6 skipped tests are tracked here as a reminder that they exist
and must be run before a production release.

---

## Security

No secrets committed. Verified by:

```bash
git grep -n "DASHSCOPE_API_KEY="   # env var name only — ok
git grep -n "QWEN_API_KEY="        # env var name only — ok
git grep -n "sk-"                  # no results
git grep -n "api_key ="            # no hardcoded values
```

`.gitignore` blocks: `.env`, `.env.local`, `.env.*.local`, `*.key`, `secrets/`
