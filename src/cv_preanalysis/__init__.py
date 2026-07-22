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
from .registration import (
    RegistrationError,
    RegistrationResult,
    crop_region,
    map_region,
    register,
    register_and_map_regions,
)
from .registry import ANALYZERS, analyzer_names, get_analyzer

__all__ = [
    "ANALYZERS",
    "CV_PROMPT_CLOSE",
    "CV_PROMPT_OPEN",
    "PreanalysisError",
    "RegistrationError",
    "RegistrationResult",
    "analyzer_names",
    "build_prompt_block",
    "crop_region",
    "get_analyzer",
    "map_region",
    "register",
    "register_and_map_regions",
    "run_preanalysis",
    "write_evidence",
    "write_overlay",
]
