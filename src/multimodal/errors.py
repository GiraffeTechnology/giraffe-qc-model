"""Error types for the multimodal QC layer."""
from __future__ import annotations


class MultimodalConfigError(Exception):
    """Raised when provider configuration is invalid or missing."""


class MultimodalProviderError(Exception):
    """Raised when a provider call fails."""


class MultimodalParseError(Exception):
    """Raised when model output cannot be parsed into expected schema."""


class MultimodalCapabilityError(Exception):
    """Raised when a capability cannot be executed."""
