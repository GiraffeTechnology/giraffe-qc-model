"""Abstract base class for QWEN QC providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    QwenInspectionOutput,
    StandardPhotoInput,
)


class QwenQCProvider(ABC):
    """Abstract base class for QWEN QC inspection providers.

    Implementations include:
    - DashScopeQwenProvider: calls DashScope cloud API
    - FakeCloudQwenProvider: deterministic fake for testing
    - FailingQwenProvider: always raises (for testing error paths)
    """

    @abstractmethod
    def inspect(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        """Run QC inspection.

        Args:
            standard_photos: Reference standard photos
            captured_photo: Production photo to inspect
            qc_points: QC criteria to evaluate
            context: Tenant/SKU/inspection context

        Returns:
            QwenInspectionOutput with results per QC point

        Raises:
            RuntimeError: If inspection fails unrecoverably
            TimeoutError: If inspection times out
        """
        ...

    @property
    def engine_name(self) -> str:
        """Short identifier for this provider engine."""
        return self.__class__.__name__
