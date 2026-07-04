"""Edge CV agent orchestration (§14.1).

``EdgeCVAgent`` wires the pieces together. It is transport-agnostic: pass any
client exposing ``.post(url, json=..., headers=...)`` (httpx.Client for a real
deployment, or a FastAPI TestClient in CI). ``run_forever`` is the real loop;
``register`` / ``heartbeat_once`` / ``poll_once`` are individually callable so
the whole lifecycle is testable without threads, sleeps, or hardware.
"""
from __future__ import annotations

import time
from typing import Optional

from edge_cv_agent.app import device_register, heartbeat, job_client, job_runner
from edge_cv_agent.app.config import AgentConfig


class EdgeCVAgent:
    def __init__(self, client, cfg: Optional[AgentConfig] = None):
        self.client = client
        self.cfg = cfg or AgentConfig()
        self.device_id: Optional[str] = None
        self.session_id: Optional[str] = None
        self.auth_token: Optional[str] = None
        self._active_jobs = 0

    # ── lifecycle ───────────────────────────────────────────────────────────
    def register(self) -> dict:
        data = device_register.register(self.client, self.cfg)
        self.device_id = data["device_id"]
        self.session_id = data["session_id"]
        self.auth_token = data["auth_token"]
        return data

    def heartbeat_once(self, status: str = "online") -> dict:
        payload = heartbeat.build_heartbeat_payload(
            self.device_id, self.session_id, mock=self.cfg.mock_mode, active_job_count=self._active_jobs, status=status
        )
        return heartbeat.send_heartbeat(self.client, self.cfg.service_url, self.auth_token, payload)

    def poll_once(self, force_scenario: str | None = None) -> Optional[dict]:
        """Pull at most one job and process it. Returns the run status or None."""
        job = job_client.pull_next(
            self.client, self.cfg.service_url, self.auth_token, self.device_id, self.session_id, self.cfg.capabilities()
        )
        if job is None:
            return None
        self._active_jobs += 1
        try:
            return job_runner.process_job(
                self.client, self.cfg, self.auth_token, self.device_id, self.session_id, job, force_scenario=force_scenario
            )
        finally:
            self._active_jobs -= 1

    # ── real loop (not used in CI) ──────────────────────────────────────────
    def run_forever(self, iterations: Optional[int] = None) -> None:  # pragma: no cover
        self.register()
        last_hb = 0.0
        count = 0
        while iterations is None or count < iterations:
            now = time.monotonic()
            if now - last_hb >= self.cfg.heartbeat_interval_seconds:
                try:
                    self.heartbeat_once()
                except Exception:
                    self.register()  # session lost → re-register (hot-plug safe)
                last_hb = now
            if self.poll_once() is None:
                time.sleep(self.cfg.poll_interval_seconds)
            count += 1


def main() -> None:  # pragma: no cover
    import httpx

    cfg = AgentConfig()
    with httpx.Client(timeout=30) as client:
        EdgeCVAgent(client, cfg).run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
