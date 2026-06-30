"""Giraffe QC Model — Phase 1 visual QC training & execution foundation.

This package is a *general-purpose*, provider-compatible, LLM/VLM-driven
visual QC **training and execution framework**. It is not a single-SKU
detector and it is not bound to any one model vendor.

Each *production* digital inspector is, by contract, SKU-specific,
workstation-specific, and bound to a confirmed Training Pack — but the
framework itself stays product-category agnostic.

Product defaults are two Qwen3.5-VL runtime profiles selected by execution
environment:

    desktop_pc_mnn -> qwen3.5-vl-2b-mnn
    server         -> qwen3.5-vl-8b-int4

Product services depend on the abstract
:class:`~src.qc_model.providers.base.VisionLanguageModelProvider` interface,
never on a Qwen-specific class, so the provider can be swapped through config.

NOTE: This package is a server-side / schema-side / orchestration foundation.
It deliberately does NOT touch the physical Android Pad MNN runtime
(``apps/android-qc``). See ``docs/QC_MODEL_PHASE1_VISUAL_QC.md``.
"""
