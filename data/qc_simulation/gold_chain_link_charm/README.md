# Gold Chain Link Charm QC Simulation Dataset

This dataset contains operator-provided real production photos for validating a
chain-link-count QC defect.

Real production samples:

- `real/standard/real_production_chain_13_links_standard_001.jpg`
- `real/fail_missing_chain_link/real_production_chain_12_links_missing_one_001.jpg`

The standard sample has 13 visible chain links. The defect sample has 12 visible
chain links and is labeled as missing one chain link.

Required detection points:

- `chain_link_count`
- `top_attachment_integrity`
- `bottom_charm_attachment_integrity`
- `link_alignment`
- `surface_finish_integrity`
- `incidental_abnormality`

These photos are marked `is_synthetic: false` and use license note
`operator_provided_real_production_photo_internal_test_only`.

Runner:

```bash
python -m src.qc_simulation.runner
```

To run this dataset directly:

```python
from pathlib import Path
from src.qc_simulation.runner import run_simulation

run_simulation(Path("data/qc_simulation/gold_chain_link_charm"))
```

This dataset does not modify Android MNN runtime logic, Pad orchestration, JNI
wiring, physical Pad testing workflows, or production provider routing.
