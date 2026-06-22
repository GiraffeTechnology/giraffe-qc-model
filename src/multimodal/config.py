"""Provider-neutral multimodal config helpers.

All values read at call time so monkeypatching works in tests.
"""
from __future__ import annotations
import os


def multimodal_provider() -> str:
    """Active provider name. Default: qwen."""
    return os.getenv("MULTIMODAL_PROVIDER", "qwen").lower()


def multimodal_enable_real_calls() -> bool:
    return os.getenv("MULTIMODAL_ENABLE_REAL_CALLS", "false").lower() == "true"


def multimodal_timeout_seconds() -> int:
    return int(os.getenv("MULTIMODAL_TIMEOUT_SECONDS", "60"))


def multimodal_max_retries() -> int:
    return int(os.getenv("MULTIMODAL_MAX_RETRIES", "2"))


def multimodal_default_model() -> str:
    return os.getenv("MULTIMODAL_DEFAULT_MODEL", "")


def qc_routing_mode() -> str:
    """local_first | cloud_first_dev | backend_proxy | mock"""
    return os.getenv("QC_ROUTING_MODE", "local_first").lower()


def qc_allow_cloud_fallback() -> bool:
    return os.getenv("QC_ALLOW_CLOUD_FALLBACK", "false").lower() == "true"


def qc_require_user_consent_for_cloud() -> bool:
    return os.getenv("QC_REQUIRE_USER_CONSENT_FOR_CLOUD", "true").lower() == "true"


def qc_allow_send_images_to_cloud() -> bool:
    return os.getenv("QC_ALLOW_SEND_IMAGES_TO_CLOUD", "false").lower() == "true"


def qc_cloud_can_override_local_fail() -> bool:
    return os.getenv("QC_CLOUD_CAN_OVERRIDE_LOCAL_FAIL", "false").lower() == "true"


def qc_min_pass_confidence() -> float:
    return float(os.getenv("QC_MIN_PASS_CONFIDENCE", "0.82"))
