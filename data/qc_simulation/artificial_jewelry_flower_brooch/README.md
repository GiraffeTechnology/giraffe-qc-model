# Artificial Jewelry Flower Brooch QC Simulation Dataset

This seed-data-driven simulation dataset is for internal QC validation only.

Selected SKU category: artificial jewelry flower brooch / hair clip with flower
petals, pearl beads, rhinestone / crystal details, and metallic stamen
structure.

Seed data source policy:

- Uses a small number of publicly accessible product-page images.
- Does not bypass login, anti-bot restrictions, paywalls, or access controls.
- Does not use the source image for public marketing.
- Source metadata is stored in `seed/source_metadata.jsonl`.
- License note: `public_product_page_internal_test_only`.

Synthetic sample categories:

- `pass`
- `fail_center_offcenter_subtle`
- `fail_missing_rhinestone_subtle`
- `fail_pearl_hairline_crack`
- `fail_missing_pearl`
- `fail_petal_micro_chip`
- `mixed_defects`

Required detection points:

- `center_alignment`
- `rhinestone_count`
- `pearl_count`
- `pearl_surface_integrity`
- `petal_integrity`
- `incidental_abnormality`

Runner:

```bash
python -m src.qc_simulation.runner
```

Report path:

```text
data/qc_simulation/artificial_jewelry_flower_brooch/reports/simulation_report.json
```

This dataset is separate from the Pre-Pad Simulation Gate and does not perform
physical Pad validation, Android MNN inference, JNI wiring, or production
provider routing.
