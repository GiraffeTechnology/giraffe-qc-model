"""Phase 2A — LLM/VLM QC rule *learning* engine skeleton.

IMPORTANT: "learning" here means **rule learning** — proposing structured
detection points, visual features, pseudo-defects, decision rules, and
review-required conditions from operator requirements + Training Pack context.

It explicitly does NOT mean:
- fine-tuning model weights / LoRA training
- full production dataset training
- automatic accuracy certification
- automatic production activation
- tablet-side rule generation

The learning loop is:

    operator QC requirement + Training Pack context
      -> LLM/VLM rule *proposal*
      -> structured learned detection points / visual rules / pseudo-defects
      -> supervisor review and confirmation
      -> approved rules become Training Pack assets

The model may propose, but it must not authorize itself. Only supervisor-
approved proposals can be applied to a Training Pack, and applying them never
auto-activates the pack or the inspector.

Runtime policy: rule learning defaults to the **server** profile
(`qwen3.5-vl-8b-int4`). The `tablet_mnn` profile is for edge-side execution of
*confirmed* rules, not for learning. The deprecated desktop edge-profile name
must never appear; the edge profile is `tablet_mnn`.
"""
