"""Inference adapter interface -- the Jetson-side seam between the §4 wire
contract and a concrete inference backend (mock or real).

This mirrors the shape and philosophy of
``src.qc_model.providers.base.VisionLanguageModelProvider`` (stable
name/model identifiers, never raise to signal a *model* failure, fail closed)
but speaks the Jetson §4 request/response contract directly
(``src.qc_model.jetson.contract``), since that is what actually crosses the
Pad<->Jetson LAN boundary -- the Server-side ``VisualInspectionRequest``
shape never reaches this device.

``JetsonRunnerService`` (``main.py``) selects exactly one adapter per process
based on ``RunnerConfig.mock_mode`` and never runs both.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from jetson_runner.app.admin_contract import AdminPointResult, AdminRecognitionRequest
from src.qc_model.jetson.contract import InferenceResponse


class InferenceAdapter(ABC):
    """All Xavier Administrator inference providers implement this seam."""

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Stable provider-adapter identifier, e.g. ``mock`` or ``mnn``."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Configured model identifier; Qwen is a default, not a product lock."""

    @property
    def model_revision(self) -> str:
        """Auditable model revision, or ``unvalidated`` when not certified."""
        return "unvalidated"

    @abstractmethod
    def is_ready(self) -> bool:
        """Whether this adapter can serve a real ``run_inference`` call right now.

        For the mock adapter this is always ``True``. For a real backend this
        must reflect the actual backend/model state (a live MNN model handle) -- ``JetsonRunnerService``
        checks this *before* calling ``run_inference`` and fails closed
        (rejects ``/infer`` with ``runtime_not_ready``) when it is ``False``,
        rather than letting a backend call fail mid-request.
        """

    @abstractmethod
    def run_inference(self, payload: dict) -> InferenceResponse:
        """Validate ``payload`` against the §4 contract, then run inference.

        Takes the raw (already pad/signature-authenticated) request dict, not
        a pre-validated object -- the mock adapter's ``mock_result`` test hint
        lives on the raw payload, not on ``DetectionPointSpec`` (it is
        deliberately not part of the wire schema real callers use), so
        validation happens inside each adapter, not before it.

        Raises ``pydantic.ValidationError`` on a malformed payload (the
        caller maps that to a rejected request, same as before adapters
        existed). Must not raise to signal a *per-point* model uncertainty --
        return a ``PerPointResult`` with ``result="uncertain"`` and
        ``confidence=0.0`` instead, so one bad point doesn't fail the whole
        job. Raising past validation is reserved for conditions the caller
        should treat as the whole request failing (e.g. the backend became
        unreachable mid-call).
        """

    def run_admin_recognition(
        self,
        request: AdminRecognitionRequest,
        image_paths: dict[str, str],
    ) -> list[AdminPointResult]:
        """Run the Architecture v2 Administrator recognition contract."""
        raise NotImplementedError("adapter does not implement Administrator recognition")
