"""Runtime edition configuration for QC Model.

QC_RUNTIME_EDITION=padLocal  → Pad (Android) edition
QC_RUNTIME_EDITION=server    → Server edition

Sample DB, admin page, SKU API, standard photos, inspection requirements,
detection points, and result schema are SHARED between editions.
Only inference behaviour (model, API/cloud access) differs per edition.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class Edition(str, Enum):
    PAD_LOCAL = "padLocal"
    SERVER = "server"


@dataclass(frozen=True)
class EditionConfig:
    edition: Edition
    model_name: str
    allow_qwen_api: bool
    allow_cloud_inference: bool


_DEFAULTS: dict[Edition, EditionConfig] = {
    Edition.PAD_LOCAL: EditionConfig(
        edition=Edition.PAD_LOCAL,
        model_name="Qwen3-VL-2B-Instruct-MNN",
        allow_qwen_api=False,
        allow_cloud_inference=False,
    ),
    Edition.SERVER: EditionConfig(
        edition=Edition.SERVER,
        model_name="Qwen3-VL-8B",
        allow_qwen_api=True,
        allow_cloud_inference=True,
    ),
}


def get_edition_config() -> EditionConfig:
    """Return runtime edition config resolved from environment variables.

    Environment variables override per-edition defaults:
      QC_RUNTIME_EDITION       - "padLocal" (default) or "server"
      QC_MODEL_NAME            - overrides the default model for the edition
      QC_ALLOW_QWEN_API        - "true"/"false", overrides edition default
      QC_ALLOW_CLOUD_INFERENCE - "true"/"false", overrides edition default
    """
    raw = os.environ.get("QC_RUNTIME_EDITION", Edition.PAD_LOCAL.value)
    try:
        edition = Edition(raw)
    except ValueError:
        edition = Edition.PAD_LOCAL

    defaults = _DEFAULTS[edition]

    def _bool(env_key: str, default: bool) -> bool:
        v = os.environ.get(env_key)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "yes")

    return EditionConfig(
        edition=edition,
        model_name=os.environ.get("QC_MODEL_NAME", defaults.model_name),
        allow_qwen_api=_bool("QC_ALLOW_QWEN_API", defaults.allow_qwen_api),
        allow_cloud_inference=_bool("QC_ALLOW_CLOUD_INFERENCE", defaults.allow_cloud_inference),
    )
