"""Run one pulled job end-to-end: validate model, run CV, upload or fail."""
from __future__ import annotations

from edge_cv_agent.app import job_client, model_loader, result_uploader
from edge_cv_agent.app.cv_pipeline import MockCVError, run_mock_pipeline


def process_job(client, cfg, auth_token: str, device_id: str, session_id: str, job: dict, force_scenario: str | None = None) -> dict:
    """Process a single leased job. Returns a small status dict for logging/tests.

    Any runtime failure (mock or real) is reported to the service via the fail
    endpoint so the dispatcher can retry / fall back / escalate — the agent
    never leaves a job silently stuck.
    """
    job_id = job["cv_job_id"]
    model_block = job.get("model")
    model_id = model_block.get("model_id") if model_block else None
    model_hash = model_block.get("model_hash") if model_block else None

    # Mark started (leased -> running).
    job_client.mark_started(client, cfg.service_url, auth_token, job_id, device_id, session_id)

    try:
        model_loader.validate_model(model_block, mock=cfg.mock_mode)
        output = run_mock_pipeline(job, scenario=force_scenario)
    except model_loader.ModelHashMismatch as exc:
        job_client.report_failure(client, cfg.service_url, auth_token, job_id, device_id, session_id, "model_hash_mismatch", str(exc))
        return {"job_id": job_id, "outcome": "failed", "error_code": "model_hash_mismatch"}
    except model_loader.ModelMissing as exc:
        job_client.report_failure(client, cfg.service_url, auth_token, job_id, device_id, session_id, "model_missing", str(exc))
        return {"job_id": job_id, "outcome": "failed", "error_code": "model_missing"}
    except MockCVError as exc:
        job_client.report_failure(client, cfg.service_url, auth_token, job_id, device_id, session_id, exc.error_code, str(exc))
        return {"job_id": job_id, "outcome": "failed", "error_code": exc.error_code}

    payload = result_uploader.build_result_payload(device_id, session_id, output, model_id=model_id, model_hash=model_hash)
    resp = result_uploader.upload_result(client, cfg.service_url, auth_token, job_id, payload)
    status = getattr(resp, "status_code", 201)
    return {"job_id": job_id, "outcome": "uploaded", "http_status": status}
