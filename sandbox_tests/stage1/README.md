# Stage 1 — single-server full pipeline

This harness executes repository fixture input (explicitly labeled simulated
capture), the shared deterministic OpenCV pre-analysis stage, configured sandbox
VLM inference, strict output parsing, and a final pass/reject decision.

> this is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.

## Local configuration

Copy `sandbox_tests/config/sandbox.env.example` to repository-root
`sandbox.env`, then fill values supplied out of band. The file is gitignored.
Never paste it into terminal output, a PR, a report, or documentation.

The harness supports two configured endpoint envelopes:

- `openai_chat`: an OpenAI-compatible multimodal chat response;
- `inspection`: the repository's server inspection JSON endpoint.

Neither endpoint, host, model name, timeout, nor sample path is hardcoded.

## Commands

Validate the 12-case manifest without network calls:

```bash
PYTHONPATH=. .venv/bin/python -m sandbox_tests.stage1.runner --validate-only
```

Execute and generate both report formats:

```bash
PYTHONPATH=. .venv/bin/python -m sandbox_tests.stage1.runner \
  --env-file sandbox.env \
  --report sandbox_tests/reports/stage1_report.json
```

Before commit, verify the configured address cannot appear in tracked files:

```bash
PYTHONPATH=. .venv/bin/python -m sandbox_tests.check_no_leaks \
  --env-file sandbox.env
```

Reports include the configured sandbox-model versus production-model delta.
They are chain-validity evidence only, never model-quality or production-readiness
evidence.
