# Sandbox QC Stage 1 Report

> this is a SANDBOX environment, not a production configuration. No test conclusion, performance number, or stability result from it may be presented as evidence of production readiness; production admission is re-evaluated only after Stage 3+4.

> Model delta: Sandbox server is specified to run `qwen3-vl-8b-int4`; production v2 specifies cloud `qwen3-vl-30b-A3B` and admin-side `qwen3-vl-4b` (MNN). These are replaceable configured defaults, not Giraffe product identity or an ecosystem dependency. Results, once executed, are chain-validity evidence, not model-quality evidence.

**Status:** `blocked` — no sandbox inference was executed and no result or timing was fabricated.

## Implemented and locally verified

- Twelve-case manifest: four categories × positive/anomalous real inference, plus model-output anomaly, timeout, format error, and injection-looking output.
- Shared deterministic OpenCV pre-analysis execution.
- Strict single-object parsing, `<think>` removal, duplicate-key rejection, trailing-content rejection, and injection-marker rejection.
- Fail-closed mapping to `reject` for transport, timeout, envelope, schema, and parsing failures.
- Stable JSON/Markdown report schema and server-address redaction check.

## Blocking items

- Repository-root `sandbox.env` is not provisioned in the Codex runtime.
- The configured sandbox service base URL including port is unavailable.
- The endpoint API style and path are not confirmed.
- The `abcdYi` SSH alias is not resolvable in the Codex macOS runtime.

After those local-only settings are supplied, run the command in
`sandbox_tests/stage1/README.md`. It overwrites this blocked report with real case
outputs and exits non-zero unless every acceptance gate passes.

## Acceptance

- [ ] End-to-end chain has no blocking error.
- [ ] Four categories each execute one positive and one anomalous sample.
- [ ] Model-output anomaly, timeout, and format error all fail closed.
- [ ] Real model `<think>` output is sanitized and parsed.
- [x] Simulated capture and injected fault elements are explicitly labeled.
- [ ] All cases pass their expected outcome.
