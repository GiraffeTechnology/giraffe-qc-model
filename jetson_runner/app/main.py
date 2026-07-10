"""Headless Jetson runner service (§6).

Ties identity + pairing + inference + health together and enforces the §7
fail-closed rule: only the *one* current paired Pad, presenting a valid
per-pair signature, may run inference. Designed to run as an auto-starting
systemd service with no login and power-cycle recovery — see README.

``handle_inference`` is pure and synchronous so the whole flow is testable
without a network or hardware; ``serve``/``main`` wire an HTTP transport for a
real deployment (LAN-only, §7).
"""
from __future__ import annotations

import time
from typing import Optional

from jetson_runner.app import health, inference_server, signing
from jetson_runner.app.config import RunnerConfig
from jetson_runner.app.identity import JetsonIdentity, generate_identity
from jetson_runner.app.pairing_agent import PairingAgent
from src.qc_model.jetson import constants as C


class InferenceRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class JetsonRunnerService:
    def __init__(self, cfg: Optional[RunnerConfig] = None, identity: Optional[JetsonIdentity] = None):
        self.cfg = cfg or RunnerConfig()
        self.identity = identity or generate_identity(self.cfg.device_id or None)
        self.pairing = PairingAgent(self.identity)
        self._last_latency_ms: Optional[int] = None
        self._model_loaded = True  # mock model is always "loaded"
        self.set_status_led("ready")

    # ── inference (§4/§7) ────────────────────────────────────────────────────
    def handle_inference(self, *, pad_device_id: str, signature: str, payload: dict) -> dict:
        """Authenticate the paired Pad, verify the signature, run inference.

        Fail-closed: an unpaired/unknown caller or a bad signature is rejected
        and no inference runs.
        """
        if not self.pairing.is_paired_to(pad_device_id):
            self.set_status_led("error")
            raise InferenceRejected("unpaired_caller")
        if not signing.verify(self.pairing.pair_key, payload, signature):
            self.set_status_led("error")
            raise InferenceRejected("bad_signature")

        start = time.monotonic()
        try:
            response = inference_server.run_inference(payload)
        except Exception as exc:  # malformed request per the §4 contract
            raise InferenceRejected(f"invalid_request:{exc}")
        self._last_latency_ms = int((time.monotonic() - start) * 1000)
        self.set_status_led("ready")
        return response

    # ── health (§6.1) — the Pad's only window into the headless Jetson ───────
    def health_report(self) -> dict:
        report = health.collect_health(
            mock=self.cfg.mock_mode,
            model_loaded=self._model_loaded,
            last_inference_latency_ms=self._last_latency_ms,
        )
        report["jetson_device_id"] = self.identity.jetson_device_id
        report["agent_version"] = self.cfg.agent_version
        return report

    # ── status LED (optional, §6.5): booting | ready | error ─────────────────
    def set_status_led(self, state: str) -> None:
        if not self.cfg.status_led_enabled:
            return
        # pragma: no cover — GPIO write on real hardware only.
        self._led_state = state  # type: ignore[attr-defined]


def main() -> None:  # pragma: no cover - real deployment entrypoint
    """Auto-start entrypoint (systemd). LAN-only HTTP inference endpoint."""
    from fastapi import FastAPI, HTTPException
    import uvicorn

    cfg = RunnerConfig()
    service = JetsonRunnerService(cfg)
    app = FastAPI(title="Jetson qc-model runner", version=cfg.agent_version)

    @app.get("/health")
    def _health():
        return service.health_report()

    @app.post("/infer")
    def _infer(body: dict):
        try:
            return service.handle_inference(
                pad_device_id=body.get("pad_device_id"),
                signature=body.get("signature", ""),
                payload=body.get("request", {}),
            )
        except InferenceRejected as exc:
            raise HTTPException(status_code=403, detail=exc.reason)

    uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port)


if __name__ == "__main__":  # pragma: no cover
    main()
