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

    def is_schema_valid(self) -> bool:
        return (
            isinstance(self.disposition, str)
            and self.disposition in VALID_DISPOSITIONS
            and isinstance(self.evidence_regions, list)
            and isinstance(self.observed_features, list)
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
    """The configured production inspection provider is not production-eligible."""


def get_production_inspection_provider() -> ProductionInspectionProvider:
    """Return the configured provider.

    ``QC_PRODUCTION_INSPECTION_PROVIDER`` selects the provider; the default is the
    non-production mock (L0). The real server VLM provider is wired in PR 26.
    """
    name = os.getenv("QC_PRODUCTION_INSPECTION_PROVIDER", "mock").lower()
    # Only the mock is registered in this PR; unknown names fall back to mock so
    # nothing silently claims production eligibility.
    return MockProductionInspectionProvider()
