"""PR 24 — Training Pack readiness & learning-completeness gate.

Makes `exam_ready` (and `active`) depend on **confirmed QC knowledge
completeness**, not just structural checks. A Training Pack must not be usable
in production until the knowledge behind it has been reviewed and confirmed, or
(only for unresolved questions) explicitly waived by a supervisor with an
append-only audit trail.
"""
