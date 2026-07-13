# MockProductionInspectionProvider below is a labeled NON-PRODUCTION MOCK for CI/dev.
"""Production inspection provider abstraction (PR 25).

A production inspection provider takes a confirmed detection point + captured
image package and returns a structured, schema-valid *recommendation* (never a
final decision). The real server-side VLM provider is integrated in a later PR
(PR 26); this PR ships the abstraction, a non-production default (L0 only), and a
production-eligibility gate.

Eligibility (PRD §3, §4.3): mock / fake / stub / skeleton / deterministic-test
providers can satisfy L0 only. Production Assisted (L2) must fail closed when the
configured provider is not production-eligible.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.db.qc_production_models import (
    DISPOSITION_PASS,
    DISPOSITION_REVIEW,
    VALID_DISPOSITIONS,
)

# Provider name markers that are never production-eligible.
_NON_PRODUCTION_MARKERS = ("mock", "fake", "stub", "skeleton", "deterministic", "test")

PROMPT_SCHEMA_VERSION = "qc-production-inspection-v1"


def is_production_eligible_provider(provider_name: str | None) -> bool:
    if not provider_name:
        return False
    p = provider_name.lower()
    return not any(marker in p for marker in _NON_PRODUCTION_MARKERS)


@dataclass
class DetectionInspectionRequest:
    detection_point_code: str
    checkpoint_category: str
    confirmed_content: dict  # normal/defect/evidence_required/review_required lists
    image_references: list[str]
    capture_metadata: dict = field(default_factory=dict)


@dataclass
class DetectionInspectionResult:
    disposition: str
    observed_features: list = field(default_factory=list)
    defect_features: list = field(default_factory=list)
    normal_features_matched: list = field(default_factory=list)
    evidence_regions: list = field(default_factory=list)
    review_required_conditions: list = field(default_factory=list)
    confidence: float = 0.0
    uncertainty: str = ""
    provider: str = ""
    model: str = ""
    #: Raw provider response captured verbatim for audit (never mutated).
    raw_response: dict = field(default_factory=dict)

    def is_schema_valid(self) -> bool:
        return (
            isinstance(self.disposition, str)
            and self.disposition in VALID_DISPOSITIONS
            and isinstance(self.evidence_regions, list)
            and isinstance(self.observed_features, list)
        )


# Minimum fields a real provider JSON response must contain (§ PR 26 schema).
_REQUIRED_RESPONSE_FIELDS = (
    "detection_point_code", "disposition", "observed_features", "defect_features",
    "normal_features_matched", "evidence_regions", "confidence", "uncertainty",
    "review_required_conditions", "provider", "model",
)


def parse_provider_response(raw: object) -> DetectionInspectionResult:
    """Validate + parse a raw provider JSON object into a result.

    Fail closed: raises ValueError for non-object / missing-field / bad-type /
    unknown-disposition output so a malformed provider response can never be
    treated as a valid recommendation.
    """
    if not isinstance(raw, dict):
        raise ValueError("provider response is not a JSON object")
    missing = [f for f in _REQUIRED_RESPONSE_FIELDS if f not in raw]
    if missing:
        raise ValueError(f"provider response missing required fields: {missing}")
    disposition = raw.get("disposition")
    if disposition not in VALID_DISPOSITIONS:
        raise ValueError(f"provider response disposition invalid: {disposition!r}")
    for list_field in ("observed_features", "defect_features", "normal_features_matched",
                       "evidence_regions", "review_required_conditions"):
        if not isinstance(raw.get(list_field), list):
            raise ValueError(f"provider response field {list_field!r} must be a list")
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("provider response confidence is not numeric") from exc
    return DetectionInspectionResult(
        disposition=disposition,
        observed_features=list(raw["observed_features"]),
        defect_features=list(raw["defect_features"]),
        normal_features_matched=list(raw["normal_features_matched"]),
        evidence_regions=list(raw["evidence_regions"]),
        review_required_conditions=list(raw["review_required_conditions"]),
        confidence=confidence,
        uncertainty=str(raw.get("uncertainty") or ""),
        provider=str(raw.get("provider") or ""),
        model=str(raw.get("model") or ""),
        raw_response=dict(raw),
    )


class ProductionInspectionProvider(ABC):
    provider_name: str = "base"
    model_name: str = ""
    #: L0-only providers set this False so production runs fail closed.
    production_eligible: bool = False

    @abstractmethod
    def inspect(self, request: DetectionInspectionRequest) -> DetectionInspectionResult:
        ...


class MockProductionInspectionProvider(ProductionInspectionProvider):
    """Deterministic non-production provider — L0 demo only.

    Never production-eligible; a Production Assisted run must refuse to use it.
    """

    provider_name = "mock_production_inspection"
    model_name = "mock"
    production_eligible = False

    def inspect(self, request: DetectionInspectionRequest) -> DetectionInspectionResult:
        # Deterministic placeholder recommendation; not for factory decisions.
        return DetectionInspectionResult(
            disposition=DISPOSITION_PASS if request.image_references else DISPOSITION_REVIEW,
            observed_features=list(request.confirmed_content.get("normal_visual_features") or []),
            normal_features_matched=list(request.confirmed_content.get("normal_visual_features") or []),
            evidence_regions=[{"note": "mock evidence", "bbox": None}],
            confidence=0.5,
            uncertainty="mock provider output (L0 only)",
        )


class ProductionProviderNotConfigured(RuntimeError):
    """The real production provider is not configured (fail closed, no mock)."""


class ProductionProviderError(RuntimeError):
    """The real provider failed or returned malformed output (fail closed)."""


class ProductionProviderSchemaError(ProductionProviderError):
    """The provider returned malformed / schema-invalid output (fail closed)."""


class ServerVLMInspectionProvider(ProductionInspectionProvider):
    """Real server-side VLM inspection provider (PR 26).

    Production-configurable via environment. Fails closed when not configured or
    when the backend returns malformed / schema-invalid output — it never falls
    back to a mock recommendation. The default model is the server runtime
    profile (``qwen3.5-vl-8b-int4``); production learning never runs on
    ``tablet_mnn``.
    """

    provider_name = "server_vlm"
    production_eligible = True

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None):
        self.base_url = (base_url if base_url is not None else os.getenv("QC_SERVER_VLM_BASE_URL", "")).rstrip("/")
        self.model_name = model or os.getenv("QC_SERVER_VLM_MODEL") or _server_profile_model()
        self.api_key = api_key if api_key is not None else os.getenv("QC_SERVER_VLM_API_KEY", "")
        self.timeout = float(os.getenv("QC_SERVER_VLM_TIMEOUT_SECONDS", "30"))

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _call_backend(self, payload: dict) -> object:
        """POST the inspection package to the server VLM and return parsed JSON.

        Isolated so tests can subclass/patch it with a configured stub that
        behaves like a real backend without a live server.
        """
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = httpx.post(
            f"{self.base_url}/v1/inspect", json=payload, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def inspect(self, request: DetectionInspectionRequest) -> DetectionInspectionResult:
        if not self.is_configured:
            raise ProductionProviderNotConfigured("production_provider_not_configured")
        payload = {
            "model": self.model_name,
            "detection_point_code": request.detection_point_code,
            "checkpoint_category": request.checkpoint_category,
            "confirmed_content": request.confirmed_content,
            "image_references": request.image_references,
            "capture_metadata": request.capture_metadata,
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        }
        import time

        from src.qc_model import observability

        started = time.monotonic()
        try:
            raw = self._call_backend(payload)
        except (ProductionProviderNotConfigured, ProductionProviderError):
            raise
        except Exception as exc:  # transport / HTTP / decode → fail closed
            raise ProductionProviderError(f"server_vlm backend error: {type(exc).__name__}") from exc
        finally:
            observability.observe_latency("server_vlm_inspect", (time.monotonic() - started) * 1000.0)
        try:
            return parse_provider_response(raw)
        except ValueError as exc:
            raise ProductionProviderSchemaError(f"server_vlm malformed output: {exc}") from exc


def _server_profile_model() -> str:
    from src.qc_model.runtime_profiles import RuntimeEnvironment, get_runtime_profile

    return get_runtime_profile(RuntimeEnvironment.SERVER.value).model


# Provider names that select the real server VLM path.
_SERVER_PROVIDER_NAMES = {"server_vlm", "qwen", "qwen3_5_vl", "qwen35vl"}


def production_provider_status() -> dict:
    """Report the configured production inspection provider's eligibility.

    Surfaces, for deployment/readiness checks: which provider is selected, its
    model, whether it is configured, whether it is production-eligible, the
    current APP_ENV, and whether a mock provider is permitted (never in
    production).
    """
    from src.config import app_env

    name = os.getenv("QC_PRODUCTION_INSPECTION_PROVIDER", "mock").strip().lower()
    if name in _SERVER_PROVIDER_NAMES:
        p = ServerVLMInspectionProvider()
        configured = p.is_configured
        eligible = bool(configured and p.production_eligible and is_production_eligible_provider(p.provider_name))
        provider_name, model = p.provider_name, p.model_name
    else:
        configured, eligible = False, False
        provider_name, model = MockProductionInspectionProvider.provider_name, MockProductionInspectionProvider.model_name
    return {
        "selected": name, "provider_name": provider_name, "model": model,
        "configured": configured, "production_eligible": eligible,
        "app_env": app_env(), "mock_allowed": app_env() != "production",
    }


def get_production_inspection_provider() -> ProductionInspectionProvider:
    """Resolve the configured production inspection provider.

    ``QC_PRODUCTION_INSPECTION_PROVIDER`` selects the provider. The real server
    VLM path never falls back to mock. Mock is L0-only and is refused in
    production mode.
    """
    from src.config import app_env

    name = os.getenv("QC_PRODUCTION_INSPECTION_PROVIDER", "mock").strip().lower()
    if name in _SERVER_PROVIDER_NAMES:
        return ServerVLMInspectionProvider()
    # mock / unknown → L0 only.
    if app_env() == "production":
        raise ProductionProviderNotConfigured(
            "production_provider_not_configured: mock provider is not allowed in production mode"
        )
    return MockProductionInspectionProvider()
