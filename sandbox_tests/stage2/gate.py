"""Hard Q1 gate for Stage 2 simulator execution."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class Stage2DecisionRequired(ValueError):
    """Raised when Stage 2 would execute without a recorded Q1 decision."""


SIMULATION_METHODS = {
    "qemu_aarch64",
    "native_container",
    "filesystem_level",
}


@dataclass(frozen=True)
class Stage2Gate:
    method: str
    external_drive_root: Path
    ui_validation_required: bool = True

    @classmethod
    def from_environment(cls) -> "Stage2Gate":
        method = os.getenv("STAGE2_SIMULATION_METHOD", "").strip()
        if method not in SIMULATION_METHODS:
            choices = ", ".join(sorted(SIMULATION_METHODS))
            raise Stage2DecisionRequired(
                f"Q1 decision required: STAGE2_SIMULATION_METHOD must be one of {choices}"
            )
        raw_root = os.getenv("STAGE2_EXTERNAL_DRIVE_ROOT", "").strip()
        if not raw_root:
            raise Stage2DecisionRequired(
                "external-volume decision required: STAGE2_EXTERNAL_DRIVE_ROOT is missing"
            )
        root = Path(raw_root)
        volumes = Path("/Volumes")
        try:
            root.relative_to(volumes)
        except ValueError as exc:
            raise Stage2DecisionRequired(
                "STAGE2_EXTERNAL_DRIVE_ROOT must be below /Volumes"
            ) from exc
        return cls(method=method, external_drive_root=root)

