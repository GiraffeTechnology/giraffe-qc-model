"""Headless Jetson runner service (§6).

Ties identity + pairing + inference + health together and enforces the §7
fail-closed rule: only the *one* current paired Pad, presenting a valid
per-pair signature, may run inference. Designed to run as an auto-starting
systemd service with no login and power-cycle recovery — see README.

``handle_inference`` is pure and synchronous so the whole flow is testable
without a network or hardware; ``serve``/``main`` wire an HTTP transport for a
real deployment (LAN-only, §7).

**Mock vs. real, unmistakably:** which inference path runs is controlled
*only* by ``RunnerConfig.mock_mode`` (env ``JETSON_MOCK_MODE``), which cannot
be true under ``APP_ENV=production`` (``config.py`` raises at construction).
Every mock-served request is logged at WARNING with the literal string
``"MOCK INFERENCE — NOT REAL QC JUDGMENT"`` so it can never be mistaken for
real output in logs. See ``docs/api-contracts/jetson-runner-api.md`` §4.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from starlette.requests import Request

from jetson_runner.app import health, signing
from jetson_runner.app.adapters.base import InferenceAdapter
from jetson_runner.app.adapters.llama_cpp_adapter import LlamaCppInferenceAdapter
from jetson_runner.app.adapters.mock_adapter import MockInferenceAdapter
from jetson_runner.app.config import RunnerConfig
from jetson_runner.app.identity import JetsonIdentity, generate_identity
from jetson_runner.app.pairing_agent import PairingAgent, PairingRejected

logger = logging.getLogger("jetson_runner")


class InferenceRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _build_adapter(cfg: RunnerConfig) -> InferenceAdapter:
    if cfg.mock_mode:
        return MockInferenceAdapter()
    return LlamaCppInferenceAdapter(
        base_url=cfg.llama_server_url,
        model_name=cfg.llama_model_name,
        timeout_seconds=cfg.llama_request_timeout_seconds,
    )


class JetsonRunnerService:
    def __init__(
        self,
        cfg: Optional[RunnerConfig] = None,
        identity: Optional[JetsonIdentity] = None,
        adapter: Optional[InferenceAdapter] = None,
    ):
        self.cfg = cfg or RunnerConfig()
        self.identity = identity or generate_identity(self.cfg.device_id or None)
        self.pairing = PairingAgent(self.identity)
        self.adapter = adapter or _build_adapter(self.cfg)
        self._last_latency_ms: Optional[int] = None
        self.set_status_led("ready")

    # ── inference (§4/§7) ────────────────────────────────────────────────────
    def handle_inference(self, *, pad_device_id: str, signature: str, payload: dict) -> dict:
        """Authenticate the paired Pad, verify the signature, run inference.

        Fail-closed at every stage: an unpaired/unknown caller or a bad
        signature is rejected before inference ever runs; a real adapter that
        is not ready (backend unreachable / no model loaded) is rejected with
        ``runtime_not_ready`` rather than being allowed to fail mid-request or
        silently fall back to mock.
        """
        if not self.pairing.is_paired_to(pad_device_id):
            self.set_status_led("error")
            raise InferenceRejected("unpaired_caller")
        if not signing.verify(self.pairing.pair_key, payload, signature):
            self.set_status_led("error")
            raise InferenceRejected("bad_signature")

        if self.cfg.mock_mode:
            logger.warning(
                "MOCK INFERENCE — NOT REAL QC JUDGMENT (job_id=%s, adapter=%s)",
                payload.get("job_id"),
                self.adapter.adapter_name,
            )
        elif not self.adapter.is_ready():
            self.set_status_led("error")
            raise InferenceRejected("runtime_not_ready")

        start = time.monotonic()
        try:
            response = self.adapter.run_inference(payload)
        except InferenceRejected:
            raise
        except Exception as exc:  # malformed request per the §4 contract, or backend failure
            raise InferenceRejected(f"invalid_request:{exc}")
        self._last_latency_ms = int((time.monotonic() - start) * 1000)
        self.set_status_led("ready")
        return response.model_dump()

    # ── health (§6.1) — the Pad's only window into the headless Jetson ───────
    def health_report(self) -> dict:
        model_loaded = True if self.cfg.mock_mode else self.adapter.is_ready()
        report = health.collect_health(
            mock=self.cfg.mock_mode,
            model_loaded=model_loaded,
            last_inference_latency_ms=self._last_latency_ms,
        )
        report["jetson_device_id"] = self.identity.jetson_device_id
        report["agent_version"] = self.cfg.agent_version
        report["adapter_name"] = self.adapter.adapter_name
        report["model_name"] = self.adapter.model_name
        return report

    # ── status LED (optional, §6.5): booting | ready | error ─────────────────
    def set_status_led(self, state: str) -> None:
        if not self.cfg.status_led_enabled:
            return
        # pragma: no cover — GPIO write on real hardware only.
        self._led_state = state  # type: ignore[attr-defined]


def build_app(cfg: RunnerConfig, service: "JetsonRunnerService"):
    """Build the FastAPI app for a given config + service.

    Split out from ``main()`` so the HTTP layer (routes, status-code mapping)
    is testable with ``fastapi.testclient.TestClient`` without starting a
    real uvicorn server -- see ``tests/test_http_endpoints.py``.
    """
    from fastapi import FastAPI, HTTPException

    app = FastAPI(title="Jetson qc-model runner", version=cfg.agent_version)

    @app.get("/health")
    def _health():
        return service.health_report()

    @app.post("/phase1/pair-loopback")
    def _phase1_pair_loopback(body: dict, request: Request):
        """Allow the local Phase 1 CV harness to pair; never enabled by default."""
        if not cfg.phase1_loopback_pairing:
            raise HTTPException(status_code=404, detail="not_found")
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1"}:
            raise HTTPException(status_code=403, detail="loopback_only")
        pad_device_id = body.get("pad_device_id", "")
        pad_pubkey = body.get("pad_pubkey", "")
        if not pad_device_id or not pad_pubkey:
            raise HTTPException(status_code=422, detail="pad_device_id_and_pad_pubkey_required")
        return service.pairing.pair_usb(pad_device_id, pad_pubkey)

    @app.post("/pair/usb")
    def _pair_usb(body: dict):
        """Real LAN pairing, USB path (physical connection is the proof of
        presence, per PairingAgent.pair_usb). The HTTP layer here cannot
        currently distinguish "arrived over the USB gadget interface" from
        "arrived over Wi-Fi LAN" -- see docs/api-contracts/jetson-runner-api.md
        §1.4. This endpoint accepts any caller; the physical-presence
        guarantee that makes the USB path meaningful is enforced by whatever
        network topology puts the USB gadget interface on its own
        unroutable link, not by this handler. Flagged, not silently assumed.
        """
        pad_device_id = body.get("pad_device_id", "")
        pad_pubkey = body.get("pad_pubkey", "")
        if not pad_device_id or not pad_pubkey:
            raise HTTPException(status_code=422, detail="pad_device_id_and_pad_pubkey_required")
        return service.pairing.pair_usb(pad_device_id, pad_pubkey)

    @app.post("/pair/wifi")
    def _pair_wifi(body: dict):
        """Real LAN pairing, Wi-Fi path: only accepted inside a pairing window
        opened by a physical trigger on the Jetson, and only with a matching
        chassis fingerprint (PairingAgent.pair_wifi)."""
        pad_device_id = body.get("pad_device_id", "")
        pad_pubkey = body.get("pad_pubkey", "")
        confirmed_fingerprint = body.get("confirmed_fingerprint", "")
        if not pad_device_id or not pad_pubkey or not confirmed_fingerprint:
            raise HTTPException(
                status_code=422,
                detail="pad_device_id_and_pad_pubkey_and_confirmed_fingerprint_required",
            )
        try:
            return service.pairing.pair_wifi(pad_device_id, pad_pubkey, confirmed_fingerprint)
        except PairingRejected as exc:
            raise HTTPException(status_code=403, detail=str(exc))

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
                raise HTTPException(status_code=503, detail=exc.reason)
            if exc.reason.startswith("invalid_request:"):
                raise HTTPException(status_code=422, detail=exc.reason)
            raise HTTPException(status_code=403, detail=exc.reason)

    return app


def main() -> None:  # pragma: no cover - real deployment entrypoint
    """Auto-start entrypoint (systemd). LAN-only HTTP inference endpoint."""
    import uvicorn

    cfg = RunnerConfig()
    service = JetsonRunnerService(cfg)
    app = build_app(cfg, service)
    uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port)


if __name__ == "__main__":  # pragma: no cover
    main()
