"""Structured result upload (§12.3)."""
from __future__ import annotations

from typing import Optional

from edge_cv_agent.app.cv_pipeline import CVOutput


def build_result_payload(device_id: str, session_id: str, output: CVOutput, model_id: Optional[str] = None, model_hash: Optional[str] = None) -> dict:
    return {
        "device_id": device_id,
        "session_id": session_id,
        "model_id": model_id,
        "result_type": output.result_type,
        "confidence": output.confidence,
        "pass_fail_hint": output.pass_fail_hint,
        "detections": output.detections,
        "measurements": output.measurements,
        "features": output.features,
        "evidence_assets": output.evidence_assets,
        "raw_output": output.raw_output,
        "model_hash": model_hash,
    }


def upload_result(client, service_url: str, auth_token: str, job_id: str, payload: dict):
    return client.post(
        f"{service_url}/api/edge-cv/jobs/{job_id}/result",
        json=payload,
        headers={"Authorization": f"Bearer {auth_token}"},
    )
