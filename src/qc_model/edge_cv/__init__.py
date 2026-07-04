"""Hot-pluggable Edge CV subsystem (optional co-processor + CPU fallback).

See docs/edge-cv-architecture.md for the design. The public surface is the
service functions in :mod:`src.qc_model.edge_cv.service`,
:mod:`src.qc_model.edge_cv.dispatcher`, :mod:`src.qc_model.edge_cv.results`,
and the CPU fallback runner in :mod:`src.qc_model.edge_cv.cpu_fallback`.
"""
