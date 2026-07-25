# qc-vlm-probe

Standalone, non-production validation harness for one question: at full
precision (no quantization) and empirically adequate sample sizes, does
`qwen3-vl-235b-a22b-instruct` reach viable jewelry QC accuracy? Four prior
no-go rounds were decided on ~4 samples each — statistically insufficient to
tell a bad model from an unlucky one. This harness exists to re-run that
question properly, or to say plainly that it still can't be answered.

This module is **not** part of the production `giraffe-qc-model` app. It does
not import from, or get imported by, `src/`. See
`PRD_VLM_VALIDATION_HARNESS_2.md` (v2, authoritative) for the full
assumption ledger (A1–A8), sample-set requirements, and report contract.

## Layout

```
qc-probe.sh           CLI: probe | sweep | run | score
lib/estimator.py       A2 local token estimator (smart_resize), stdlib+Pillow
lib/score.py            Offline scorer: report.json + report.md, zero API calls
prompts/                v2_structured_json.txt, v3_with_reference.txt
config/models.tsv       Pricing/vision config per model (TBD fails loudly)
config/gates.env        Pass/fail thresholds (blank = INCONCLUSIVE, not guessed)
samples/                Runtime-only: images + ground_truth.jsonl (gitignored)
results/                Runtime-only: raw responses + reports (gitignored)
tests/                  Unit tests — no network, no API key required
```

## Before a real run

1. Fill in `config/models.tsv`'s two `TBD` price cells with the current list
   price from the Bailian console (list price only — no negotiated discount
   belongs in this repo).
2. Decide the acceptable false-accept / false-reject rates for this QC line
   and set them in `config/gates.env`. Until set, every verdict is
   `INCONCLUSIVE` by design.
3. Assemble `samples/ground_truth.jsonl` and the sample image tree (≥80
   samples across the defect distribution in the PRD, 3 angles each, labelled
   by two independent labellers with third-party disagreement resolution).

## Usage

```
./qc-probe.sh probe  --api-key-file ~/.bailian.key --images ./samples/images
./qc-probe.sh sweep  --api-key-file ~/.bailian.key --image ./samples/images/ref_front.jpg
./qc-probe.sh run    --api-key-file ~/.bailian.key --images ./samples/images \
                      --max-pixels default --n-images 3 --prompt v2_structured_json
./qc-probe.sh score  --run <run_id>
```

`--api-key-file` and `BAILIAN_BASE_URL` are supplied only at invocation. They
are never hardcoded, committed, logged, or written to any result file.

## Tests

```
python3 -m unittest discover -s tests -v
```

No network access and no API key required — these test the estimator math,
tiered pricing, Wilson confidence intervals, the raw-response parser against
corrupted/malformed fixtures, and a repo-hygiene guard (no IP addresses or
hardcoded API keys anywhere under this directory).
