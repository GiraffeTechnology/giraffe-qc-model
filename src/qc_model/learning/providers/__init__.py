"""Rule-learning provider abstraction.

Product learning services depend only on
:class:`~src.qc_model.learning.providers.base.QCRuleLearningProvider` and the
registry. Concrete vendor classes (Qwen3.5-VL, mainstream stubs) are resolved
lazily by the registry, never imported by product logic.
"""
from src.qc_model.learning.providers.base import QCRuleLearningProvider

__all__ = ["QCRuleLearningProvider"]
