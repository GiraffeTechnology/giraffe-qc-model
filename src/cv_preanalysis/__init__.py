"""Deterministic classical-CV pre-analysis shared by Nano and Xavier.

The package produces supporting evidence only.  It never emits or changes a
quality verdict; the configured VLM and the server verdict policy remain the
judges.
"""

from .pipeline import (
    CV_PROMPT_CLOSE,
    CV_PROMPT_OPEN,
    PreanalysisError,
    build_prompt_block,
    run_preanalysis,
    write_evidence,
    write_overlay,
)
from .registry import ANALYZERS, analyzer_names, get_analyzer

__all__ = [
    "ANALYZERS",
    "CV_PROMPT_CLOSE",
    "CV_PROMPT_OPEN",
    "PreanalysisError",
    "analyzer_names",
    "build_prompt_block",
    "get_analyzer",
    "run_preanalysis",
    "write_evidence",
    "write_overlay",
]
