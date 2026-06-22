"""Abstract multimodal provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.multimodal.types import MultimodalRequest, MultimodalRawResponse


class MultimodalProvider(ABC):
    """All product logic depends only on this interface."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def generate(self, request: MultimodalRequest) -> MultimodalRawResponse: ...
