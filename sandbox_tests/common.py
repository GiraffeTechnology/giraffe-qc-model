"""Shared configuration and declarations for sandbox-only reports."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


SANDBOX_DECLARATION = (
    "this is a SANDBOX environment, not a production configuration. No test "
    "conclusion, performance number, or stability result from it may be presented "
    "as evidence of production readiness; production admission is re-evaluated "
    "only after Stage 3+4."
)


class SandboxConfigurationError(ValueError):
    """The required local-only sandbox configuration is absent or unsafe."""


def load_env_file(path: str | Path) -> None:
    """Load a simple local env file without ever logging values."""
    source = Path(path)
    if not source.is_file():
        raise SandboxConfigurationError(
            f"local sandbox env file is missing: {source.name}; copy config/sandbox.env.example"
        )
    for line_number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SandboxConfigurationError(f"invalid env syntax at line {line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.startswith("SANDBOX_"):
            raise SandboxConfigurationError(f"non-sandbox key refused at line {line_number}")
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("replace-with-"):
        raise SandboxConfigurationError(f"required local setting is missing: {name}")
    return value


@dataclass(frozen=True)
class SandboxConfig:
    server: str
    model: str
    api_style: str
    inference_path: str
    api_key: str
    timeout_seconds: float
    max_image_bytes: int
    max_output_chars: int
    production_cloud_model: str
    production_admin_model: str

    @classmethod
    def from_environment(cls) -> "SandboxConfig":
        server = _required("SANDBOX_QC_SERVER").rstrip("/")
        parsed = urlparse(server)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SandboxConfigurationError("SANDBOX_QC_SERVER must be an http(s) base URL")
        style = os.getenv("SANDBOX_QC_API_STYLE", "openai_chat").strip()
        if style not in {"openai_chat", "inspection"}:
            raise SandboxConfigurationError("SANDBOX_QC_API_STYLE must be openai_chat or inspection")
        inference_path = os.getenv("SANDBOX_QC_INFERENCE_PATH", "").strip()
        if not inference_path.startswith("/") or "://" in inference_path:
            raise SandboxConfigurationError("SANDBOX_QC_INFERENCE_PATH must be a relative absolute path")
        timeout = float(os.getenv("SANDBOX_QC_TIMEOUT_SECONDS", "60"))
        max_bytes = int(os.getenv("SANDBOX_QC_MAX_IMAGE_BYTES", "5242880"))
        max_output = int(os.getenv("SANDBOX_QC_MAX_OUTPUT_CHARS", "100000"))
        if timeout <= 0 or max_bytes <= 0 or max_output <= 0:
            raise SandboxConfigurationError("sandbox timeout and size limits must be positive")
        return cls(
            server=server,
            model=_required("SANDBOX_QC_MODEL"),
            api_style=style,
            inference_path=inference_path,
            api_key=os.getenv("SANDBOX_QC_API_KEY", ""),
            timeout_seconds=timeout,
            max_image_bytes=max_bytes,
            max_output_chars=max_output,
            production_cloud_model=_required("SANDBOX_PRODUCTION_CLOUD_MODEL"),
            production_admin_model=_required("SANDBOX_PRODUCTION_ADMIN_MODEL"),
        )

    @property
    def model_delta_note(self) -> str:
        return (
            f"Sandbox server runs {self.model}; production v2 specifies cloud "
            f"{self.production_cloud_model} and admin-side {self.production_admin_model} "
            "(MNN). These are replaceable configured defaults, not Giraffe product "
            "identity or an ecosystem dependency. Results are chain-validity evidence, "
            "not model-quality evidence."
        )
