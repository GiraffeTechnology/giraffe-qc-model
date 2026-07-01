"""Unified Training Pack ownership resolver (Production Readiness §4.4).

There is no central Training Pack registry table; a pack's tenant ownership is
derived from the tenant-scoped rows that reference it. This module is the single
source of truth for that derivation so every PR21–PR24 service/router resolves
ownership consistently and fails closed for unknown / cross-tenant packs.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearningJob
from src.db.qc_readiness_models import QCReadinessWaiver
from src.db.qc_sample_learning_models import (
    CaptureArtifactRule,
    PseudoDefectRule,
    QCConfirmedVisualRule,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
)
from src.db.qc_source_models import QCSourceDocument

# Every tenant-scoped table that references a training_pack_id. Ownership is the
# union of tenants that have any row here for the pack.
_PACK_OWNED_TABLES = (
    QCSourceDocument,
    QCLearningJob,
    RuleAuthoringJob,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
    QCConfirmedVisualRule,
    PseudoDefectRule,
    CaptureArtifactRule,
    QCReadinessWaiver,
)


class CrossTenantTrainingPack(ValueError):
    """A training_pack_id is already owned by a different tenant."""


def pack_owner_tenants(db: Session, training_pack_id: str) -> set[str]:
    """Return the set of tenant_ids that reference this training pack."""
    owners: set[str] = set()
    for model in _PACK_OWNED_TABLES:
        owners.update(
            r[0]
            for r in db.query(model.tenant_id)
            .filter(model.training_pack_id == training_pack_id)
            .distinct()
            .all()
        )
    return owners


def pack_known_for_tenant(db: Session, training_pack_id: str, tenant_id: str) -> bool:
    """True if this tenant owns any data referencing the pack.

    Unknown packs — or packs owned only by other tenants — return False so the
    readiness gate and lookups fail closed rather than passing vacuous
    empty-query checks.
    """
    for model in _PACK_OWNED_TABLES:
        exists = (
            db.query(model.id)
            .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id)
            .first()
        )
        if exists is not None:
            return True
    return False


def assert_pack_accessible(db: Session, training_pack_id: str, tenant_id: str) -> None:
    """Raise CrossTenantTrainingPack if the pack is owned only by other tenants.

    First use by a tenant binds the id to that tenant. A pack that is unknown to
    everyone is accessible (first-touch); a pack known only under other tenants
    is not.
    """
    owners = pack_owner_tenants(db, training_pack_id)
    if owners and tenant_id not in owners:
        raise CrossTenantTrainingPack(
            f"training_pack_id {training_pack_id!r} is not accessible for tenant {tenant_id!r}"
        )
