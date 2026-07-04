"""Heartbeat payload + send (§8.2)."""
from __future__ import annotations

from edge_cv_agent.app.health import collect_metrics


def build_heartbeat_payload(device_id: str, session_id: str, *, mock: bool = True, active_job_count: int = 0, status: str = "online") -> dict:
    return {
        "device_id": device_id,
        "session_id": session_id,
        "status": status,
        "active_job_count": active_job_count,
        "metrics": collect_metrics(mock=mock, active_job_count=active_job_count),
    }


def send_heartbeat(client, service_url: str, auth_token: str, payload: dict) -> dict:
    resp = client.post(
        f"{service_url}/api/edge-cv/devices/heartbeat",
        json=payload,
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    return resp.json()
