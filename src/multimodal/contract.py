"""
Shared QC contract constants.

QC_CONTRACT_VERSION is the handshake string embedded in every inspection
request and result. Both the server (Python) and Pad (Kotlin SharedQcContract)
must agree on this value. A mismatch must be logged — never silently accepted.

This module is intentionally standalone: no imports from src/multimodal/types.py
or other sibling modules, so it can be imported without the full multimodal
stack being present (e.g. on main before the multimodal layer is merged).
"""

QC_CONTRACT_VERSION: str = "multimodal-qc-v1"

VALID_RESULTS: frozenset[str] = frozenset({"pass", "fail", "review_required"})

# Forbidden values that must never appear in any production result.
# Any provider returning these must have its output normalised to review_required.
FORBIDDEN_RESULTS: frozenset[str] = frozenset({
    "ok", "ng", "unknown", "needs_fix", "good", "bad",
})


def normalize_result(value: str | None) -> str:
    """Return a canonical result string. Unknown/null → review_required (fail-closed)."""
    if value in VALID_RESULTS:
        return value  # type: ignore[return-value]
    return "review_required"
