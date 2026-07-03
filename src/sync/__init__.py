"""Offline standard-sync: signed bundle export + idempotent result ingest (Task 03).

Server → Pad: build versioned, signed standard bundles from ACTIVE standard
revisions. Pad → Server: idempotent batch upload of completed inspection jobs
onto the generation-3 pipeline. Real-time push is NOT supported by design — the
production Pad is offline during inspections.
"""
