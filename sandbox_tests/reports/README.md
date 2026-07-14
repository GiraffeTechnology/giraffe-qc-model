# Sandbox reports

Reports in this directory use one stable schema across Stages 1–4. Generate
Stage 1 only after the repository-root, gitignored `sandbox.env` is provisioned:

```bash
PYTHONPATH=. .venv/bin/python -m sandbox_tests.stage1.runner \
  --env-file sandbox.env \
  --report sandbox_tests/reports/stage1_report.json
```

The command writes both JSON and Markdown. It exits non-zero when any acceptance
gate is false. Never hand-edit a generated report to turn a failure into a pass.

> this is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.
