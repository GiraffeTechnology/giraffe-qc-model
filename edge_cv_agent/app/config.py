"""Agent configuration, loaded from environment (§14.2)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, "true" if default else "false").lower() == "true"


@dataclass
class AgentConfig:
    device_name: str = field(default_factory=lambda: os.getenv("EDGE_AGENT_DEVICE_NAME", "jetson-nano-2gb-lab-001"))
    device_type: str = field(default_factory=lambda: os.getenv("EDGE_AGENT_DEVICE_TYPE", "jetson_nano_2gb"))
    service_url: str = field(default_factory=lambda: os.getenv("EDGE_AGENT_SERVICE_URL", "http://localhost:8000"))
    tenant_id: str = field(default_factory=lambda: os.getenv("EDGE_AGENT_TENANT_ID", "default"))
    poll_interval_seconds: float = field(default_factory=lambda: float(os.getenv("EDGE_AGENT_POLL_INTERVAL_SECONDS", "3")))
    heartbeat_interval_seconds: float = field(default_factory=lambda: float(os.getenv("EDGE_AGENT_HEARTBEAT_INTERVAL_SECONDS", "10")))
    max_concurrent_jobs: int = field(default_factory=lambda: int(os.getenv("EDGE_AGENT_MAX_CONCURRENT_JOBS", "1")))
    model_dir: str = field(default_factory=lambda: os.getenv("EDGE_AGENT_MODEL_DIR", "/opt/giraffe/models"))
    output_dir: str = field(default_factory=lambda: os.getenv("EDGE_AGENT_OUTPUT_DIR", "/opt/giraffe/cv_outputs"))
    mock_mode: bool = field(default_factory=lambda: _bool("EDGE_AGENT_MOCK_MODE", True))
    bootstrap_token: str = field(default_factory=lambda: os.getenv("EDGE_AGENT_BOOTSTRAP_TOKEN", ""))
    agent_version: str = "0.1.0"

    def capabilities(self) -> list[str]:
        return [
            "opencv",
            "image_preprocess",
            "object_detection",
            "defect_candidate_detection",
            "crop_generation",
            "annotated_image_generation",
            "live_candidate_lock_capture",
        ]
