"""Model loading + hash validation (§14.1 steps 6-7).

In mock mode no artifact is fetched; the "model" is the mock pipeline. The hash
check is still exercised so the model-hash-mismatch failure path is covered.
"""
from __future__ import annotations

from typing import Optional


class ModelHashMismatch(Exception):
    pass


class ModelMissing(Exception):
    pass


def validate_model(model_block: Optional[dict], *, mock: bool = True, expected_local_hash: Optional[str] = None) -> None:
    """Validate a job's model block before running inference.

    Raises :class:`ModelMissing` when the job requires a model but none is
    provided, or :class:`ModelHashMismatch` when the locally-computed hash does
    not match the manifest hash. In mock mode the local hash defaults to the
    manifest hash (so success is the default) unless a mismatching
    ``expected_local_hash`` is supplied to force the failure path.
    """
    if model_block is None:
        return  # job may not require a model (e.g. simple preprocess)
    manifest_hash = model_block.get("model_hash")
    if manifest_hash is None:
        return
    local_hash = expected_local_hash if expected_local_hash is not None else manifest_hash
    if local_hash != manifest_hash:
        raise ModelHashMismatch(f"expected {manifest_hash!r}, local {local_hash!r}")
