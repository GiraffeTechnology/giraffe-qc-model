"""PR 22 — LLM QC rule authoring from source fragments.

Converts PR 21 ``QCSourceFragment`` rows into structured *learned rule
proposals* using an LLM. Proposals are DRAFT only — supervisor approval is
mandatory before anything can apply to a Training Pack (PR 20's approval
workflow is reused). This PR implements NO Training Pack application and has no
code path that writes to Training Pack tables.

Two safety invariants are enforced in code (not just prompts):
- Physical-measurement guard: a ``physical_measurement`` checkpoint is ALWAYS
  ``record_only``, regardless of what the LLM returns (see ``validator``).
- Never guess missing values (count, tolerance, required view, orientation,
  color range, measurement method, threshold): raise a
  ``questions_or_ambiguities`` entry instead of inventing a value.
"""
