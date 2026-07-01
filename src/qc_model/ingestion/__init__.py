"""QC Source Ingestion Workbench (PR 21).

Ingest QC source materials (drawings, specs, standards, samples, natural-
language / speech operator input) and run a **deterministic / mocked**
extraction step that produces *draft fragments only*.

Nothing produced here can become an active rule. There is no ``active`` status
at this layer — everything is ``draft`` / ``reviewed`` / ``rejected``. The
deterministic extractor is a placeholder for the real LLM/VLM extraction that
arrives in a later PR (PR 22/23).
"""
