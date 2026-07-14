"""Real Administrator-side VLM adapter backed by a native MNN bridge.

The adapter is deliberately provider-neutral.  The deployment default model
is qwen3-vl-4b, but callers only depend on this ``mnn`` adapter contract and
the configured model identity.  A compatible MNN-exported VLM can replace the
default without changing the HTTP API or product terminology.

This module does not pretend that a model is loaded because files exist.  The
native bridge owns the live model handle and ``is_ready`` queries that handle.
No real-device performance or accuracy claim is made until the manual Xavier
validation in ``jetson_runner/HARDWARE_VALIDATION.md`` has been completed.
"""
from __future__ import annotations

import ctypes
import json
import logging
import re
from pathlib import Path
from typing import Protocol

from jetson_runner.app.adapters.base import InferenceAdapter
from jetson_runner.app.admin_contract import (
    AdminDetectionPoint,
    AdminPointResult,
    AdminRecognitionRequest,
    EvidenceRegion,
)
from src.qc_model.jetson import constants as C
from src.qc_model.jetson.contract import InferenceResponse, PerPointResult, validate_request
from src.cv_preanalysis import build_prompt_block

logger = logging.getLogger("jetson_runner")
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_OUTPUT_CAPACITY = 64 * 1024

_SYSTEM_PROMPT = (
    "You are assisting an administrator with a manufacturing visual-quality "
    "review. Judge exactly one detection point from the supplied image. "
    "Return only JSON with result (pass, fail, or uncertain), confidence "
    "(0 to 1), evidence, and optional evidence_regions. Use uncertain when "
    "the image or evidence is insufficient; never guess."
)


class MnnRuntime(Protocol):
    """Small injectable seam around the native, persistent MNN model handle."""

    @property
    def last_error(self) -> str: ...

    def is_ready(self) -> bool: ...

    def infer(self, *, image_path: str, prompt: str) -> str: ...


class CtypesMnnRuntime:
    """Load the Xavier C ABI bridge and retain one live model instance."""

    def __init__(self, *, bridge_library: str, model_dir: str) -> None:
        self._library = None
        self._handle = None
        self._last_error = "runtime_not_loaded"
        try:
            library = ctypes.CDLL(bridge_library)
            library.giraffe_mnn_create.argtypes = [ctypes.c_char_p]
            library.giraffe_mnn_create.restype = ctypes.c_void_p
            library.giraffe_mnn_is_ready.argtypes = [ctypes.c_void_p]
            library.giraffe_mnn_is_ready.restype = ctypes.c_int
            library.giraffe_mnn_infer.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_size_t,
            ]
            library.giraffe_mnn_infer.restype = ctypes.c_int
            library.giraffe_mnn_last_error.argtypes = [ctypes.c_void_p]
            library.giraffe_mnn_last_error.restype = ctypes.c_char_p
            library.giraffe_mnn_destroy.argtypes = [ctypes.c_void_p]
            library.giraffe_mnn_destroy.restype = None
            handle = library.giraffe_mnn_create(model_dir.encode("utf-8"))
            if not handle:
                self._last_error = "native bridge could not create the MNN model"
                return
            self._library = library
            self._handle = handle
            if not self.is_ready():
                self._last_error = self._read_native_error() or "MNN model is not ready"
        except (OSError, AttributeError, ValueError) as exc:
            self._last_error = f"MNN bridge load failed: {exc}"

    @property
    def last_error(self) -> str:
        if self._handle:
            return self._read_native_error() or self._last_error
        return self._last_error

    def is_ready(self) -> bool:
        if not self._library or not self._handle:
            return False
        try:
            return bool(self._library.giraffe_mnn_is_ready(self._handle))
        except Exception as exc:  # pragma: no cover - native boundary
            self._last_error = f"MNN readiness query failed: {exc}"
            return False

    def infer(self, *, image_path: str, prompt: str) -> str:
        if not self.is_ready():
            raise RuntimeError(self.last_error or "MNN runtime is not ready")
        output = ctypes.create_string_buffer(_OUTPUT_CAPACITY)
        rc = self._library.giraffe_mnn_infer(
            self._handle,
            image_path.encode("utf-8"),
            prompt.encode("utf-8"),
            output,
            len(output),
        )
        if rc != 0:
            raise RuntimeError(self._read_native_error() or f"MNN inference failed ({rc})")
        return output.value.decode("utf-8", errors="replace")

    def _read_native_error(self) -> str:
        if not self._library or not self._handle:
            return ""
        try:
            raw = self._library.giraffe_mnn_last_error(self._handle)
            return raw.decode("utf-8", errors="replace") if raw else ""
        except Exception:  # pragma: no cover - native boundary
            return ""

    def close(self) -> None:
        if self._library and self._handle:
            self._library.giraffe_mnn_destroy(self._handle)
            self._handle = None

    def __del__(self) -> None:  # pragma: no cover - interpreter/native teardown
        try:
            self.close()
        except Exception:
            pass


class MnnVlmAdapter(InferenceAdapter):
    def __init__(
        self,
        *,
        bridge_library: str,
        model_dir: str,
        model_name: str,
        runtime: MnnRuntime | None = None,
    ) -> None:
        self._model_name = model_name
        self._model_dir = Path(model_dir)
        self._runtime = runtime or CtypesMnnRuntime(
            bridge_library=bridge_library, model_dir=model_dir
        )
        self._model_revision = self._read_model_revision()

    @property
    def adapter_name(self) -> str:
        return "mnn"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_revision(self) -> str:
        return self._model_revision

    @property
    def last_error(self) -> str:
        return self._runtime.last_error

    def is_ready(self) -> bool:
        return self._runtime.is_ready()

    def run_inference(self, payload: dict) -> InferenceResponse:
        """Temporary compatibility for the superseded Operator endpoint."""
        request = validate_request(payload)
        results: list[PerPointResult] = []
        for point in request.detection_points:
            prompt = self._legacy_prompt(point)
            try:
                parsed = self._parse_model_output(
                    self._runtime.infer(image_path=request.image, prompt=prompt)
                )
                parsed.pop("evidence_regions", None)
                results.append(PerPointResult(point_code=point.point_code, **parsed))
            except Exception as exc:
                results.append(
                    PerPointResult(
                        point_code=point.point_code,
                        result=C.RESULT_UNCERTAIN,
                        confidence=0.0,
                        evidence=f"MNN adapter error: {exc}",
                    )
                )
        return InferenceResponse(job_id=request.job_id, per_point_results=results)

    def run_admin_recognition(
        self,
        request: AdminRecognitionRequest,
        image_paths: dict[str, str],
    ) -> list[AdminPointResult]:
        if not self.is_ready():
            raise RuntimeError(self.last_error or "MNN runtime is not ready")
        results: list[AdminPointResult] = []
        for point in request.detection_points:
            try:
                raw = self._runtime.infer(
                    image_path=image_paths[point.image_id],
                    prompt=self._admin_prompt(point),
                )
                parsed = self._parse_model_output(raw)
                regions = [EvidenceRegion.model_validate(r) for r in parsed.pop("evidence_regions", [])]
                results.append(
                    AdminPointResult(
                        point_code=point.point_code,
                        evidence_regions=regions,
                        cv_status=point.cv_status,
                        cv_analysis=point.cv_analysis,
                        **parsed,
                    )
                )
            except Exception as exc:
                logger.warning("MNN point output rejected point_code=%s: %s", point.point_code, exc)
                results.append(
                    AdminPointResult(
                        point_code=point.point_code,
                        result="uncertain",
                        confidence=0.0,
                        evidence=f"MNN output unavailable or invalid: {exc}",
                        cv_status=point.cv_status,
                        cv_analysis=point.cv_analysis,
                    )
                )
        return results

    def _read_model_revision(self) -> str:
        manifest = self._model_dir / "model_manifest.json"
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            revision = value.get("revision") or value.get("model_revision")
            return str(revision) if revision else "unvalidated"
        except (OSError, ValueError, TypeError):
            return "unvalidated"

    @staticmethod
    def _legacy_prompt(point) -> str:
        return (
            f"{_SYSTEM_PROMPT}\nDetection point: {point.point_code}\n"
            f"Label: {point.label}\nDescription: {point.description}\n"
            f"Expected value: {point.expected_value}\nPass criteria: {point.pass_criteria}\n"
        )

    @staticmethod
    def _admin_prompt(point: AdminDetectionPoint) -> str:
        lines = [
            _SYSTEM_PROMPT,
            f"Detection point: {point.point_code}",
            f"Label: {point.label}",
            f"Description: {point.description}",
            f"Expected value: {point.expected_value}",
            f"Pass criteria: {point.pass_criteria}",
            f"Severity: {point.severity}",
            "Regions: " + json.dumps([r.model_dump() for r in point.regions], separators=(",", ":")),
        ]
        if point.expected_features is not None:
            lines.append(
                "Expected features: "
                + json.dumps(point.expected_features, sort_keys=True, separators=(",", ":"))
            )
        if point.cv_status == "completed" and point.cv_analysis is not None:
            lines.append(build_prompt_block(point.cv_analysis))
        return "\n".join(lines)

    @staticmethod
    def _parse_model_output(text: str) -> dict:
        match = _JSON_OBJECT_RE.search(text or "")
        if not match:
            raise ValueError("no JSON object found")
        value = json.loads(match.group(0))
        result = value.get("result")
        if result not in C.INFERENCE_RESULTS:
            raise ValueError(f"invalid result: {result!r}")
        try:
            confidence = max(0.0, min(1.0, float(value.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        regions = value.get("evidence_regions", [])
        if not isinstance(regions, list):
            regions = []
        return {
            "result": result,
            "confidence": confidence,
            "evidence": str(value.get("evidence", ""))[:2000],
            "evidence_regions": regions,
        }
