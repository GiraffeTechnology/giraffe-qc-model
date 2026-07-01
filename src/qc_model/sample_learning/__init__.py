"""PR 23 — VLM sample-learning foundation.

Learns structured **visual rule memory** from grouped sample images
(reference / positive / defect / boundary / capture-artifact), producing draft
visual observations that require supervisor approval before they can be applied
to a Training Pack.

Global hard requirements honored here:
- No auto-activation; supervisor approval is mandatory.
- Approve and apply are TWO distinct steps; apply is the only Training-Pack
  writer and rejects non-approved memory server-side.
- Applying never silently overwrites an existing confirmed rule (conflict →
  rejected, requires explicit supervisor resolution).
- Provider failure / malformed output fails closed (no approvable output).
- Tenant isolation on every lookup. Per-sample provenance is preserved
  (never collapsed into aggregate-only records).
- Mocked tests prove workflow only, not real visual accuracy.
"""
