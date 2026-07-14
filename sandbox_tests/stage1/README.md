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

The deployed checkout also uses `.env.stage1.local` (mode `0600`) for
`QC_DB_URL`, `SAMPLE_STORE_DIR`, `CAPTURE_DIR`, and `STAGE1_DATA_ROOT`. Its
database URL targets an isolated CTYUN MySQL schema. Runtime samples and
captures live under the checkout's ignored `data/` directory. Neither secret
file is committed.

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
  --runtime-env .env.stage1.local \
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

The Stage 1 acceptance gate also verifies that the deployed source checkout is
present, the ignored project-local data directory is writable, and the
configured CTYUN database is reachable through the MySQL dialect with the QC
schema initialized. Reports expose no endpoint, username, password, or URL.
