"""Pull-based job client (§12.3): next / start / fail."""
from __future__ import annotations

from typing import Optional


def _headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


def pull_next(client, service_url: str, auth_token: str, device_id: str, session_id: str, capabilities: list[str]) -> Optional[dict]:
    resp = client.post(
        f"{service_url}/api/edge-cv/jobs/next",
        json={"device_id": device_id, "session_id": session_id, "capabilities": capabilities},
        headers=_headers(auth_token),
    )
    data = resp.json()
    return data.get("job")


def mark_started(client, service_url: str, auth_token: str, job_id: str, device_id: str, session_id: str) -> dict:
    resp = client.post(
        f"{service_url}/api/edge-cv/jobs/{job_id}/start",
        json={"device_id": device_id, "session_id": session_id},
        headers=_headers(auth_token),
    )
    return resp.json()


def report_failure(client, service_url: str, auth_token: str, job_id: str, device_id: str, session_id: str, error_code: str, error_message: str = "") -> dict:
    resp = client.post(
        f"{service_url}/api/edge-cv/jobs/{job_id}/fail",
        json={"device_id": device_id, "session_id": session_id, "error_code": error_code, "error_message": error_message},
        headers=_headers(auth_token),
    )
    return resp.json()
