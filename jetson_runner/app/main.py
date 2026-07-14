"""Headless Xavier NX runner for Architecture v2 Administrator workflows.

The supported v2 path is MNN-based and provider-neutral. Qwen is the default
configured VLM, not a required ecosystem or API identity. Legacy Pad-to-Xavier
routes remain temporarily for migration and are explicitly outside the v2
Operator production path.
"""
from __future__ import annotations

import hashlib
import logging
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from jetson_runner.app import health, signing
from jetson_runner.app.adapters.base import InferenceAdapter
from jetson_runner.app.adapters.mnn_adapter import MnnVlmAdapter
from jetson_runner.app.adapters.mock_adapter import MockInferenceAdapter
from jetson_runner.app.admin_auth import (
    EMPTY_SHA256,
    AdminAuthRejected,
    AdminAuthenticator,
    multipart_content_sha256,
)
from jetson_runner.app.admin_contract import (
    AdminRecognitionResponse,
    RecognitionTiming,
    RuntimeIdentity,
    validate_admin_request,
)
from jetson_runner.app.config import RunnerConfig
from jetson_runner.app.identity import JetsonIdentity, generate_identity
from jetson_runner.app.pairing_agent import PairingAgent, PairingRejected

logger = logging.getLogger("jetson_runner")
MOCK_BANNER = "MOCK INFERENCE — NOT REAL QC JUDGMENT"


class InferenceRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AdminRequestRejected(Exception):
    def __init__(self, code: str, http_status: int):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def _build_adapter(cfg: RunnerConfig) -> InferenceAdapter:
    if cfg.mock_mode:
        return MockInferenceAdapter()
    return MnnVlmAdapter(
        bridge_library=cfg.mnn_bridge_library,
        model_dir=cfg.mnn_model_dir,
        model_name=cfg.mnn_model_name,
    )


class JetsonRunnerService:
    def __init__(
        self,
        cfg: Optional[RunnerConfig] = None,
        identity: Optional[JetsonIdentity] = None,
        adapter: Optional[InferenceAdapter] = None,
        authenticator: Optional[AdminAuthenticator] = None,
    ):
        self.cfg = cfg or RunnerConfig()
        self.identity = identity or generate_identity(self.cfg.device_id or None)
        self.pairing = PairingAgent(self.identity)
        self.adapter = adapter or _build_adapter(self.cfg)
        self.authenticator = authenticator or AdminAuthenticator(
            self.cfg.admin_credentials,
            max_clock_skew_seconds=self.cfg.auth_clock_skew_seconds,
            nonce_ttl_seconds=self.cfg.auth_nonce_ttl_seconds,
        )
        self._legacy_last_latency_ms: Optional[int] = None
        self._loaded_at = health.utc_now() if self.adapter.is_ready() else None
        self._last_recognition: dict | None = None
        self._recognitions: OrderedDict[str, tuple[str, dict]] = OrderedDict()
        self._recognition_cache_lock = threading.Lock()
        self._admin_inference_lock = threading.Lock()
        self.set_status_led("ready" if self.adapter.is_ready() else "error")

    def authenticate_admin(
        self, *, method: str, path: str, headers, digest: str, request_id: str = ""
    ):
        try:
            return self.authenticator.authenticate(
                method=method,
                path=path,
                headers=headers,
                content_sha256=digest,
                request_id=request_id,
            )
        except AdminAuthRejected as exc:
            raise AdminRequestRejected(exc.code, exc.http_status) from exc

    def handle_admin_recognition(
        self,
        *,
        manifest: dict,
        content_digest: str,
        image_paths: dict[str, str],
        request_received_at: str,
    ) -> dict:
        try:
            request = validate_admin_request(manifest)
        except Exception as exc:
            raise AdminRequestRejected("invalid_request", 422) from exc

        prior = self._get_cached_recognition(request.request_id)
        if prior:
            if prior[0] != content_digest:
                raise AdminRequestRejected("idempotency_conflict", 409)
            return prior[1]
        if not self._admin_inference_lock.acquire(blocking=False):
            raise AdminRequestRejected("runner_busy", 429)
        try:
            # Recheck after acquiring the single-runtime lock so two concurrent
            # copies of one idempotency key cannot both run the model.
            prior = self._get_cached_recognition(request.request_id)
            if prior:
                if prior[0] != content_digest:
                    raise AdminRequestRejected("idempotency_conflict", 409)
                return prior[1]
            return self._execute_admin_recognition(
                request=request,
                content_digest=content_digest,
                image_paths=image_paths,
                request_received_at=request_received_at,
            )
        finally:
            self._admin_inference_lock.release()

    def _execute_admin_recognition(
        self,
        *,
        request,
        content_digest: str,
        image_paths: dict[str, str],
        request_received_at: str,
    ) -> dict:
        if not self.adapter.is_ready():
            raise AdminRequestRejected("runtime_not_ready", 503)

        if self.cfg.mock_mode:
            logger.warning("%s (request_id=%s)", MOCK_BANNER, request.request_id)
        inference_started_at = health.utc_now()
        started = time.monotonic()
        try:
            point_results = self.adapter.run_admin_recognition(request, image_paths)
        except Exception as exc:
            logger.exception("Administrator recognition runtime failure request_id=%s", request.request_id)
            raise AdminRequestRejected("runtime_not_ready", 503) from exc
        inference_completed_at = health.utc_now()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        response_sent_at = health.utc_now()
        response = AdminRecognitionResponse(
            request_id=request.request_id,
            point_results=point_results,
            runtime=RuntimeIdentity(
                model_name=self.adapter.model_name,
                model_revision=self.adapter.model_revision,
                adapter_mode="mock" if self.cfg.mock_mode else "real",
            ),
            timing=RecognitionTiming(
                request_received_at=request_received_at,
                inference_started_at=inference_started_at,
                inference_completed_at=inference_completed_at,
                response_sent_at=response_sent_at,
            ),
            mock=self.cfg.mock_mode,
        ).model_dump()
        if self.cfg.mock_mode:
            # Make the mock nature unmissable at the response envelope as well
            # as in every per-point evidence string and log record.
            response["warning"] = MOCK_BANNER
        self._cache_recognition(request.request_id, content_digest, response)
        self._last_recognition = {
            "status": "completed",
            "finished_at": inference_completed_at,
            "latency_ms": None if self.cfg.mock_mode else elapsed_ms,
        }
        return response

    def get_admin_recognition(self, request_id: str) -> dict | None:
        entry = self._get_cached_recognition(request_id)
        return entry[1] if entry else None

    def _get_cached_recognition(self, request_id: str) -> tuple[str, dict] | None:
        with self._recognition_cache_lock:
            entry = self._recognitions.get(request_id)
            if entry is not None:
                self._recognitions.move_to_end(request_id)
            return entry

    def _cache_recognition(self, request_id: str, content_digest: str, response: dict) -> None:
        """Retain only the most recent reconciliation responses.

        Responses contain per-point evidence and can be large, so the in-memory
        idempotency window must stay bounded for a long-running Xavier service.
        Durable reconciliation across restarts remains a deployment follow-up.
        """
        with self._recognition_cache_lock:
            self._recognitions[request_id] = (content_digest, response)
            self._recognitions.move_to_end(request_id)
            while len(self._recognitions) > self.cfg.recognition_cache_max_entries:
                self._recognitions.popitem(last=False)

    def admin_health_report(self) -> dict:
        model_loaded = self.adapter.is_ready()
        if model_loaded and self._loaded_at is None:
            self._loaded_at = health.utc_now()
        return health.collect_admin_health(
            runner_id=self.identity.jetson_device_id,
            agent_version=self.cfg.agent_version,
            adapter_mode="mock" if self.cfg.mock_mode else "real",
            model_name=self.adapter.model_name,
            model_revision=self.adapter.model_revision,
            model_loaded=model_loaded,
            loaded_at=self._loaded_at,
            credentials_configured=bool(self.cfg.admin_credentials),
            last_recognition=self._last_recognition,
            hardware_validation_status=self.cfg.hardware_validation_status,
            hardware_validation_evidence_ref=self.cfg.hardware_validation_evidence_ref,
        )

    # Legacy v1 route retained only until WS4 removes Pad-to-Xavier Operator use.
    def handle_inference(self, *, pad_device_id: str, signature: str, payload: dict) -> dict:
        if not self.pairing.is_paired_to(pad_device_id):
            raise InferenceRejected("unpaired_caller")
        if not signing.verify(self.pairing.pair_key, payload, signature):
            raise InferenceRejected("bad_signature")
        if self.cfg.mock_mode:
            logger.warning("%s (job_id=%s)", MOCK_BANNER, payload.get("job_id"))
        elif not self.adapter.is_ready():
            raise InferenceRejected("runtime_not_ready")
        started = time.monotonic()
        try:
            response = self.adapter.run_inference(payload)
        except Exception as exc:
            raise InferenceRejected(f"invalid_request:{exc}") from exc
        self._legacy_last_latency_ms = int((time.monotonic() - started) * 1000)
        return response.model_dump()

    def health_report(self) -> dict:
        """Compatibility projection for the legacy `/health` endpoint."""
        report = self.admin_health_report()
        legacy_ready = self.adapter.is_ready()
        return {
            "service_up": report["service_up"],
            "model_loaded": report["runtime"]["model_loaded"],
            # Legacy server sync still expects this top-level key until WS4
            # removes the Pad-to-Xavier compatibility path. The value remains
            # truthful: it is projected from measured v2 device telemetry and
            # stays null when the Xavier temperature cannot be observed.
            "temperature_c": report["device"]["temperature_c"],
            "readiness_state": "jetson_ready" if legacy_ready else "jetson_connecting",
            "mock": report["mock"],
            "jetson_device_id": report["runner_id"],
            "agent_version": report["agent_version"],
            "adapter_name": self.adapter.adapter_name,
            "model_name": self.adapter.model_name,
        }

    def set_status_led(self, state: str) -> None:
        if self.cfg.status_led_enabled:  # pragma: no cover - hardware only
            self._led_state = state  # type: ignore[attr-defined]


def build_app(cfg: RunnerConfig, service: JetsonRunnerService):
    app = FastAPI(title="Giraffe Administrator MNN runner", version=cfg.agent_version)

    def error(code: str, status: int):
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": code}})

    @app.get("/livez")
    def _livez():
        return {"service_up": True}

    @app.get("/api/v2/admin-runner/health")
    def _admin_health(request: Request):
        try:
            service.authenticate_admin(
                method="GET", path=request.url.path, headers=request.headers, digest=EMPTY_SHA256
            )
        except AdminRequestRejected as exc:
            return error(exc.code, exc.http_status)
        return service.admin_health_report()

    @app.post("/api/v2/admin-runner/recognitions")
    async def _admin_recognize(
        request: Request,
        manifest: str = Form(...),
        images: list[UploadFile] = File(...),
    ):
        import json

        received_at = health.utc_now()
        try:
            raw_manifest = json.loads(manifest)
            if not isinstance(raw_manifest, dict):
                raise ValueError("manifest must be an object")
            digest = multipart_content_sha256(raw_manifest)
            request_id = str(raw_manifest.get("request_id", ""))
            service.authenticate_admin(
                method="POST",
                path=request.url.path,
                headers=request.headers,
                digest=digest,
                request_id=request_id,
            )
            parsed = validate_admin_request(raw_manifest)
        except AdminRequestRejected as exc:
            return error(exc.code, exc.http_status)
        except Exception:
            return error("invalid_request", 422)

        specs_by_part = {spec.part: spec for spec in parsed.images}
        if len(specs_by_part) != len(parsed.images):
            return error("invalid_request", 422)
        uploads_by_name = {upload.filename or "": upload for upload in images}
        if set(uploads_by_name) != set(specs_by_part):
            return error("invalid_request", 422)

        with tempfile.TemporaryDirectory(prefix="giraffe-admin-") as directory:
            image_paths: dict[str, str] = {}
            total = 0
            for index, spec in enumerate(parsed.images):
                upload = uploads_by_name[spec.part]
                data = await upload.read(cfg.max_request_bytes + 1)
                total += len(data)
                if total > cfg.max_request_bytes:
                    return error("image_too_large", 413)
                if len(data) != spec.encoded_bytes or hashlib.sha256(data).hexdigest() != spec.sha256:
                    return error("image_digest_mismatch", 422)
                if upload.content_type != spec.content_type or not spec.content_type.startswith("image/"):
                    return error("invalid_request", 422)
                suffix = Path(spec.part).suffix[:10]
                path = Path(directory) / f"image-{index}{suffix}"
                path.write_bytes(data)
                image_paths[spec.image_id] = str(path)
            try:
                return await run_in_threadpool(
                    service.handle_admin_recognition,
                    manifest=raw_manifest,
                    content_digest=digest,
                    image_paths=image_paths,
                    request_received_at=received_at,
                )
            except AdminRequestRejected as exc:
                return error(exc.code, exc.http_status)

    @app.get("/api/v2/admin-runner/recognitions/{request_id}")
    def _admin_reconcile(request_id: str, request: Request):
        try:
            service.authenticate_admin(
                method="GET",
                path=request.url.path,
                headers=request.headers,
                digest=EMPTY_SHA256,
                request_id=request_id,
            )
        except AdminRequestRejected as exc:
            return error(exc.code, exc.http_status)
        response = service.get_admin_recognition(request_id)
        return response if response is not None else error("recognition_not_found", 404)

    # ---- Legacy v1 migration endpoints ---------------------------------
    @app.get("/health")
    def _health():
        return service.health_report()

    @app.post("/phase1/pair-loopback")
    def _phase1_pair_loopback(body: dict, request: Request):
        if not cfg.phase1_loopback_pairing:
            raise HTTPException(status_code=404, detail="not_found")
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1"}:
            raise HTTPException(status_code=403, detail="loopback_only")
        if not body.get("pad_device_id") or not body.get("pad_pubkey"):
            raise HTTPException(status_code=422, detail="pad_device_id_and_pad_pubkey_required")
        return service.pairing.pair_usb(body["pad_device_id"], body["pad_pubkey"])

    @app.post("/pair/usb")
    def _pair_usb(body: dict):
        if not body.get("pad_device_id") or not body.get("pad_pubkey"):
            raise HTTPException(status_code=422, detail="pad_device_id_and_pad_pubkey_required")
        return service.pairing.pair_usb(body["pad_device_id"], body["pad_pubkey"])

    @app.post("/pair/wifi")
    def _pair_wifi(body: dict):
        if not body.get("pad_device_id") or not body.get("pad_pubkey") or not body.get("confirmed_fingerprint"):
            raise HTTPException(
                status_code=422,
                detail="pad_device_id_and_pad_pubkey_and_confirmed_fingerprint_required",
            )
        try:
            return service.pairing.pair_wifi(
                body["pad_device_id"], body["pad_pubkey"], body["confirmed_fingerprint"]
            )
        except PairingRejected as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/infer")
    def _infer(body: dict):
        try:
            return service.handle_inference(
                pad_device_id=body.get("pad_device_id"),
                signature=body.get("signature", ""),
                payload=body.get("request", {}),
            )
        except InferenceRejected as exc:
            if exc.reason == "runtime_not_ready":
                raise HTTPException(status_code=503, detail=exc.reason) from exc
            if exc.reason.startswith("invalid_request:"):
                raise HTTPException(status_code=422, detail=exc.reason) from exc
            raise HTTPException(status_code=403, detail=exc.reason) from exc

    return app


def main() -> None:  # pragma: no cover - deployment entrypoint
    import uvicorn

    cfg = RunnerConfig()
    service = JetsonRunnerService(cfg)
    uvicorn.run(build_app(cfg, service), host=cfg.bind_host, port=cfg.bind_port)


if __name__ == "__main__":  # pragma: no cover
    main()
