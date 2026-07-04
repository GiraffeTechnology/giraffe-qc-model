"""Device registration (§8.1). Builds the payload and calls the service."""
from __future__ import annotations

from typing import Optional

from edge_cv_agent.app.config import AgentConfig


def build_register_payload(cfg: AgentConfig) -> dict:
    return {
        "tenant_id": cfg.tenant_id,
        "device_name": cfg.device_name,
        "device_type": cfg.device_type,
        "agent_version": cfg.agent_version,
        "capabilities": cfg.capabilities(),
        "max_concurrent_jobs": cfg.max_concurrent_jobs,
        "runtime": {"cuda": not cfg.mock_mode, "tensorrt": False, "opencv": True},
    }


def register(client, cfg: AgentConfig) -> dict:
    """POST /api/edge-cv/devices/register. Returns the parsed response dict.

    ``client`` is any object with ``.post(url, json=..., headers=...)`` returning
    an object with ``.json()`` (e.g. httpx.Client or a FastAPI TestClient). When
    a bootstrap token is configured it is sent as ``X-Edge-CV-Bootstrap-Token``.
    """
    headers = {}
    if cfg.bootstrap_token:
        headers["X-Edge-CV-Bootstrap-Token"] = cfg.bootstrap_token
    resp = client.post(
        f"{cfg.service_url}/api/edge-cv/devices/register",
        json=build_register_payload(cfg),
        headers=headers,
    )
    return resp.json()
