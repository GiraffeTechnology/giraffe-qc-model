"""Real inference adapter: calls a local llama.cpp server (llama-server).

**Scaffold, not a certified pipeline.** Per
``JETSON_NX_RUNTIME_FEASIBILITY.md`` (Option C, human-selected) and
``docs/api-contracts/jetson-runner-api.md``, the target runtime is a 2B-tier
VLM served by llama.cpp's OpenAI-compatible HTTP server on JetPack 5.1.x --
but that reflash has not happened, so this adapter has never been exercised
against a real model or real hardware. It exists so ``JETSON_MOCK_MODE=false``
has a real, complete, fail-closed code path to load -- not so this PR can
claim measured accuracy or latency it does not have.

Deliberately calls llama-server over loopback HTTP rather than binding a
Python llama.cpp package into this process: JetPack 4.6.1's system Python is
3.6, this service runs under a separate 3.11 venv, and there is no prebuilt
wheel bridging that gap for this hardware/CUDA combination (see the
feasibility doc's "Python binding version" finding). llama-server is a
separate OS process/service; this adapter only speaks HTTP to it.
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

from src.qc_model.jetson import constants as C
from src.qc_model.jetson.contract import InferenceResponse, PerPointResult, validate_request
from jetson_runner.app.adapters.base import InferenceAdapter

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM_PROMPT = (
    "You are a manufacturing QC visual inspector. You will be shown one "
    "captured image and asked to judge ONE detection point against its "
    "specification. Respond with ONLY a single JSON object, no prose, no "
    "markdown fences: "
    '{"result": "pass"|"fail"|"uncertain", "confidence": <0.0-1.0>, '
    '"evidence": "<one sentence, what you observed>"}. '
    'Use "uncertain" whenever the image is unclear, the point is not visible, '
    "or you are not confident -- never guess pass or fail."
)


class _HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _HttpClient(Protocol):
    """Duck-typed subset of ``httpx.Client`` -- lets tests inject a fake."""

    def get(self, url: str, *, timeout: float) -> _HttpResponse: ...

    def post(self, url: str, *, json: dict, timeout: float) -> _HttpResponse: ...


def _default_http_client() -> _HttpClient:
    import httpx

    return httpx.Client()


class LlamaCppAdapterError(RuntimeError):
    """The llama-server backend was unreachable or returned an unusable response."""


class LlamaCppInferenceAdapter(InferenceAdapter):
    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        timeout_seconds: float = 30.0,
        http_client: _HttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout_seconds
        self._http = http_client or _default_http_client()

    @property
    def adapter_name(self) -> str:
        return "llama_cpp"

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_ready(self) -> bool:
        """True only if llama-server answers /health with 200.

        Fail-closed: any exception (connection refused, timeout, DNS, ...) or
        non-200 status is "not ready" -- never assume readiness on error.
        """
        try:
            resp = self._http.get(f"{self._base_url}/health", timeout=self._timeout)
        except Exception:
            return False
        return resp.status_code == 200

    def run_inference(self, payload: dict) -> InferenceResponse:
        """Validate the §4 contract, then run one backend call per point.

        A per-point backend/parse failure downgrades that point to
        ``uncertain`` (never a silent pass/fail) without failing the rest of
        the job. A point missing entirely from the response is likewise
        ``uncertain``, never dropped.
        """
        req = validate_request(payload)
        results: list[PerPointResult] = []
        for dp in req.detection_points:
            try:
                raw_text = self._call_backend(dp, req.image)
                parsed = self._parse_model_output(raw_text)
            except Exception as exc:  # backend/parse failure -> uncertain, not a crash
                results.append(
                    PerPointResult(
                        point_code=dp.point_code,
                        result=C.RESULT_UNCERTAIN,
                        confidence=0.0,
                        evidence=f"llama_cpp adapter error for {dp.point_code}: {exc}",
                    )
                )
                continue
            results.append(
                PerPointResult(
                    point_code=dp.point_code,
                    result=parsed["result"],
                    confidence=parsed["confidence"],
                    evidence=parsed["evidence"],
                )
            )
        return InferenceResponse(job_id=req.job_id, per_point_results=results)

    def _call_backend(self, dp, image: str) -> str:
        user_text = (
            f"Detection point: {dp.point_code}\n"
            f"Label: {dp.label}\n"
            f"Description: {dp.description}\n"
            f"Expected value: {dp.expected_value}\n"
            f"Pass criteria: {dp.pass_criteria}\n"
            f"Severity: {dp.severity}\n"
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image}},
                ],
            },
        ]
        try:
            resp = self._http.post(
                f"{self._base_url}/v1/chat/completions",
                json={"model": self._model_name, "messages": messages, "temperature": 0.0},
                timeout=self._timeout,
            )
        except Exception as exc:
            raise LlamaCppAdapterError(f"backend unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise LlamaCppAdapterError(f"backend returned HTTP {resp.status_code}")
        body = resp.json()
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlamaCppAdapterError(f"unexpected backend response shape: {exc}") from exc

    @staticmethod
    def _parse_model_output(text: str) -> dict:
        match = _JSON_OBJECT_RE.search(text or "")
        if not match:
            raise LlamaCppAdapterError("no JSON object found in model output")
        obj = json.loads(match.group(0))
        result = obj.get("result")
        if result not in C.INFERENCE_RESULTS:
            raise LlamaCppAdapterError(f"invalid result value: {result!r}")
        try:
            confidence = float(obj.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = str(obj.get("evidence", ""))[:2000]
        return {"result": result, "confidence": confidence, "evidence": evidence}
