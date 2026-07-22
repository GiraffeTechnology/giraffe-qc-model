# Stage 2 Live Acceptance Audit — 2026-07-23

**Status:** blocked pending review and merge of the corrective pull request.

This is a live Stage 2 product-acceptance record. It does not authorize Stage 3.
Model names below identify replaceable deployment defaults, not product identity
or ecosystem dependencies.

## Acceptance boundary

- Sample entry and detection-point confirmation occur in Sample Management.
- Training and publishing occur in Digital QC Studio.
- CV is authoritative for counting. The configured 4B vision assistant only
  supports CV comparison and obvious visible-defect review.
- The configured 9B text assistant structures administrator-supplied standards;
  it must not invent inspection facts.

## Run evidence

| Step | Evidence | Result |
| --- | --- | --- |
| Clean start | Previous demo sample, photo, requirement and conversation rows were removed before the run. | Pass |
| Sample entry | A new flower-accessory SKU was created in Sample Management. | Pass |
| USB capture | The administrator manually captured the reference object. | Pass |
| Upload confirmation | The captured 1280×720 reference photo was explicitly uploaded and rendered as the primary standard photo. | Pass |
| Natural-language standard | Exact criteria supplied: 4 petals, 3 pearls, 7 rhinestones, and centered flower core. | Fail; draft rejected |

## Defect S2-LIVE-001 — unsafe 9B structured draft

The live text-assistant turn completed in **207.4 seconds**. The draft:

- classified all three exact-count criteria as generic defect detection;
- did not preserve the exact counts as executable `expected_value` fields;
- duplicated the pearl/rhinestone missing conditions even though the exact-count
  criteria already cover missing components; and
- duplicated flower-core centering as a separate offset checkpoint.

The administrator review gate worked: the draft exposed both **Confirm** and
**Reject**, and the invalid draft was rejected. No detection point was activated.

## Corrective scope

- Preserve only counts explicitly present in administrator input.
- Normalize those points to `counting` and attach the corresponding allow-listed
  CV analyzers, including `pearl_count`.
- Coalesce complementary duplicates for an already explicit exact-count or
  centering criterion.
- Keep missing counts unknown and require administrator input; never infer them.
- Tighten the 9B authoring contract so the model returns one checkpoint per
  independently testable criterion.

## Verification

- Focused text-assistant and administrator-workbench suite: **70 passed**.
- Final full repository suite: **1,318 passed, 6 skipped, 0 failed**.
- A second live 9B verification produced exactly four points with the expected
  count values and production CV analyzer assignments in **89.0 seconds**.
  Its remaining flower-core tolerance question was preserved for administrator input.
- Live acceptance remains paused until the corrective PR is reviewed and merged.
- Both observed 9B latencies (207.4 seconds before correction and 89.0 seconds
  after correction) remain recorded; more samples are required before claiming a stable latency improvement.
