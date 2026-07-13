"""Admin Studio service — chat-first SKU creation + standard training (S2).

This module is a thin orchestration layer over the existing, already-hardened
building blocks:

* SKU catalog        — :mod:`src.db.sku_models`
* standard intake    — :mod:`src.intake.service` (deterministic extraction,
                        confirmation into a standard revision)
* signed L2 bundle   — :class:`src.db.studio_models.QCPublishBundle`

It deliberately does not re-implement extraction, confirmation, or upload
handling; it wires the chat surface to them and adds the two Studio-specific
concerns: chat intent routing (create SKU vs. describe requirements) and the
signed publish bundle manifest.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.sku_models import (
    QCDetectionPoint,
    QCSkuItem,
    QCSkuStandardRevision,
    QCStandardPhoto,
)
from src.db.studio_models import QCPublishBundle
from src.intake.service import create_standard_intake, extract_standard_draft
from src.qc_model.bundle import ed25519 as _ed
from src.qc_model.qualification import probation as _probation


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# On-disk home for the canonical signed ``.tar.gz`` a publish produces. Mirrors
# the Studio photo store (``data/qc_studio/{tenant}/...``) so a bundle's payload
# lives beside the photos it embeds and stays tenant-scoped on disk.
_STUDIO_DATA_DIR = Path("data/qc_studio")


def _bundle_archive_path(tenant_id: str, bundle_id: str) -> Path:
    return _STUDIO_DATA_DIR / tenant_id / "bundles" / f"{bundle_id}.tar.gz"


# ── Chat result ───────────────────────────────────────────────────────────────


@dataclass
class StudioChatResult:
    """Structured result of one Admin Studio chat turn."""
    reply: str
    action: str  # created_sku | selected_sku | extracted | follow_up | need_sku | info
    sku: Optional[Dict[str, Any]] = None
    intake_id: Optional[str] = None
    confirmation_card: Optional[Dict[str, Any]] = None
    questions: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reply": self.reply,
            "action": self.action,
            "sku": self.sku,
            "intake_id": self.intake_id,
            "confirmation_card": self.confirmation_card,
            "questions": self.questions,
        }


# ── SKU creation intent ───────────────────────────────────────────────────────

_CREATE_SKU_RE = re.compile(
    r"^\s*(?:create|new|add|register|make)\s+(?:a\s+)?(?:new\s+)?"
    r"(?:sku|product|item|part)\b[:\-\s]*(?P<rest>.*)$",
    re.IGNORECASE,
)
# A token that looks like an item / part number: contains a digit and only
# code characters (no spaces).  e.g. FLW-001, SHIRT-CUSTOM-001, ABC_12.
_ITEM_CODE_RE = re.compile(r"^(?=[A-Za-z0-9_\-/]*\d)[A-Za-z0-9_\-/]{2,}$")
_NAMED_RE = re.compile(r"\b(?:called|named|name)\s+(?P<name>.+)$", re.IGNORECASE)


def looks_like_sku_creation(message: str) -> bool:
    return bool(_CREATE_SKU_RE.match(message or ""))


def _slug_item_number(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").upper()
    return slug or "SKU"


def parse_sku_creation(message: str) -> Optional[Dict[str, str]]:
    """Parse ``create sku FLW-001 Flower Brooch`` → item_number + name.

    Supports:
      * ``create sku <CODE> <Name...>``  (explicit item code first)
      * ``create sku <Name...> called <X>`` / ``named <X>``
      * ``create sku <Name...>``          (item number slugged from name)
    Returns None if the message is not a creation command.
    """
    m = _CREATE_SKU_RE.match(message or "")
    if not m:
        return None
    rest = m.group("rest").strip()
    if not rest:
        return None

    item_number: Optional[str] = None
    name: Optional[str] = None

    tokens = rest.split()
    if tokens and _ITEM_CODE_RE.match(tokens[0]):
        item_number = tokens[0]
        name = " ".join(tokens[1:]).strip() or None

    named = _NAMED_RE.search(rest)
    if named:
        name = named.group("name").strip().strip("\"'")
        if item_number is None:
            # everything before "called/named" is a code candidate or the name
            head = rest[: named.start()].strip()
            head_tokens = head.split()
            if head_tokens and _ITEM_CODE_RE.match(head_tokens[0]) and len(head_tokens) == 1:
                item_number = head_tokens[0]

    if name is None:
        name = rest
    if item_number is None:
        item_number = _slug_item_number(name)

    return {"item_number": item_number, "name": name}


# ── Countable-feature follow-up augmentation ──────────────────────────────────
#
# The deterministic intake parser only emits a counting checkpoint when a
# number is present (e.g. "pearl count 3").  When the admin mentions a
# countable feature *without* a number ("pearls and rhinestones"), we must ask
# for the count rather than guess it.  We add a pending checkpoint (expected
# value unknown) plus an operator follow-up question.

_COUNTABLES: List[tuple] = [
    ("pearl", "PEARL_COUNT", "Pearl Count", "Count of pearls must match expected value."),
    ("rhinestone", "RHINESTONE_COUNT", "Rhinestone Count", "Count of rhinestones must match expected value."),
    ("button", "BUTTON_COUNT", "Button Count", "Button count must match expected value."),
    ("hole", "HOLE_COUNT", "Hole Count", "Number of holes must match expected value."),
]


def _augment_missing_counts(text: str, extracted: Dict[str, Any]) -> bool:
    """Add pending count checkpoints + questions for count-less mentions.

    Returns True if the extraction was modified.
    """
    lowered = (text or "").lower()
    checkpoints = extracted.setdefault("checkpoints", [])
    questions = extracted.setdefault("questions_for_operator", [])
    existing = {c.get("point_code") for c in checkpoints}
    changed = False
    for keyword, code, label, criteria in _COUNTABLES:
        if code in existing:
            continue  # deterministic parser already captured it *with* a count
        if re.search(rf"\b{keyword}s?\b", lowered):
            checkpoints.append({
                "point_code": code,
                "label": label,
                "description": criteria,
                "method_hint": "counting",
                "severity": "critical",
                "expected_value": None,
                "pass_criteria": criteria,
            })
            questions.append({
                "field": f"{code}.expected_value",
                "question": (
                    f"How many {keyword}s are expected? Please confirm the exact "
                    f"count for {label} — it will not be guessed."
                ),
            })
            existing.add(code)
            changed = True
    return changed


# ── SKU helpers ───────────────────────────────────────────────────────────────


def sku_summary(db: Session, sku: QCSkuItem) -> Dict[str, Any]:
    """Right-panel SKU card summary including active revision + standard state."""
    active = (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=sku.id, tenant_id=sku.tenant_id, status="active")
        .order_by(QCSkuStandardRevision.revision_no.desc())
        .first()
    )
    primary = None
    for p in sku.photos:
        if p.is_primary:
            primary = p
            break
    if primary is None and sku.photos:
        primary = sku.photos[0]

    detection_points: List[Dict[str, Any]] = []
    if active is not None:
        dps = (
            db.query(QCDetectionPoint)
            .filter_by(standard_revision_id=active.id, is_active=True)
            .order_by(QCDetectionPoint.sort_order)
            .all()
        )
        detection_points = [_dp_view(dp) for dp in dps]

    if active is None:
        standard_status = "no_standard"
    elif detection_points:
        standard_status = "standard_active"
    else:
        standard_status = "standard_empty"

    return {
        "id": sku.id,
        "item_number": sku.item_number,
        "name": sku.name,
        "category": sku.category,
        "description": sku.description,
        "status": sku.status,
        "standard_status": standard_status,
        "active_revision_id": active.id if active else None,
        "active_revision_no": active.revision_no if active else None,
        "primary_photo": _photo_view(primary) if primary else None,
        "photos": [_photo_view(p) for p in sku.photos],
        "detection_points": detection_points,
        "detection_point_count": len(detection_points),
    }


def photo_url(p: QCStandardPhoto) -> str:
    """Tenant-aware URL for serving a stored standard photo.

    The serving route filters by ``tenant_id`` and defaults it to ``default``,
    so the owning tenant must be carried explicitly or non-default previews
    404. The photo knows its own tenant, so we always emit it here.
    """
    tenant = p.tenant_id or "default"
    return f"/admin/studio/photos/{p.id}?tenant_id={quote(tenant, safe='')}"


def _photo_view(p: QCStandardPhoto) -> Dict[str, Any]:
    return {
        "id": p.id,
        "url": photo_url(p),
        "view_type": p.view_type,
        "angle": p.angle,
        "sha256": p.sha256,
        "mime_type": p.mime_type,
        "is_primary": p.is_primary,
    }


def _dp_view(dp: QCDetectionPoint) -> Dict[str, Any]:
    return {
        "id": dp.id,
        "point_code": dp.point_code,
        "label": dp.label,
        "description": dp.description,
        "method_hint": dp.method_hint,
        "expected_value": dp.expected_value,
        "pass_criteria": dp.pass_criteria,
        "severity": dp.severity,
        "sort_order": dp.sort_order,
        "regions": dp.regions_json or [],
    }


def _create_sku(db: Session, tenant_id: str, item_number: str, name: str,
                category: Optional[str] = None) -> QCSkuItem:
    now = _now()
    sku = QCSkuItem(
        id=_uid(),
        tenant_id=tenant_id,
        item_number=item_number,
        name=name,
        category=category,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(sku)
    db.commit()
    db.refresh(sku)
    return sku


# ── Chat orchestration ────────────────────────────────────────────────────────


def process_studio_chat(
    db: Session,
    tenant_id: str,
    message: str,
    current_sku_id: Optional[str] = None,
    operator_id: Optional[str] = None,
) -> StudioChatResult:
    """Route one Admin Studio chat message (§5.2 / §5.4)."""
    message = (message or "").strip()
    if not message:
        return StudioChatResult(
            reply="Please type a message — name a new SKU to create it, or "
                  "describe the QC requirements for the selected SKU.",
            action="info",
        )

    # ── §5.2: SKU creation via chat ───────────────────────────────────────
    if looks_like_sku_creation(message):
        parsed = parse_sku_creation(message)
        if parsed:
            existing = (
                db.query(QCSkuItem)
                .filter_by(tenant_id=tenant_id, item_number=parsed["item_number"])
                .first()
            )
            if existing is not None:
                summary = sku_summary(db, existing)
                return StudioChatResult(
                    reply=(
                        f"SKU {existing.item_number} ({existing.name}) already exists "
                        f"— current standard status: {summary['standard_status']}. "
                        f"You can update the standard, revise detection points, "
                        f"publish to Pad, or review its history."
                    ),
                    action="selected_sku",
                    sku=summary,
                )
            try:
                sku = _create_sku(db, tenant_id, parsed["item_number"], parsed["name"])
            except IntegrityError:
                db.rollback()
                existing = (
                    db.query(QCSkuItem)
                    .filter_by(tenant_id=tenant_id, item_number=parsed["item_number"])
                    .first()
                )
                return StudioChatResult(
                    reply=f"SKU {parsed['item_number']} already exists.",
                    action="selected_sku",
                    sku=sku_summary(db, existing) if existing else None,
                )
            return StudioChatResult(
                reply=(
                    f"Created draft SKU {sku.item_number} — “{sku.name}”. "
                    f"Upload a standard photo and tell me the QC requirements "
                    f"(e.g. pearl count, rhinestone count, alignment, defects)."
                ),
                action="created_sku",
                sku=sku_summary(db, sku),
            )

    # ── §5.4: requirement extraction (needs a selected SKU) ───────────────
    sku = None
    if current_sku_id:
        sku = db.query(QCSkuItem).filter_by(id=current_sku_id, tenant_id=tenant_id).first()
    if sku is None:
        return StudioChatResult(
            reply=(
                "Select a SKU from the left, or create one first "
                "(e.g. “create sku FLW-001 Flower Brooch”)."
            ),
            action="need_sku",
        )

    intake = create_standard_intake(
        db,
        sku_id=sku.id,
        tenant_id=tenant_id,
        raw_text=message,
        source_type="admin_studio",
        source_channel="studio_chat",
        operator_id=operator_id,
    )
    intake = extract_standard_draft(db, intake.id)

    extracted = dict(intake.extracted_json or {})
    if _augment_missing_counts(message, extracted):
        intake.extracted_json = extracted
        payload = dict(intake.confirmation_payload_json or {})
        payload["checkpoints"] = extracted["checkpoints"]
        payload["questions_for_operator"] = extracted["questions_for_operator"]
        intake.confirmation_payload_json = payload
        db.commit()
        db.refresh(intake)

    checkpoints = extracted.get("checkpoints", [])
    questions = extracted.get("questions_for_operator", [])

    if not checkpoints:
        return StudioChatResult(
            reply=(
                "I couldn't identify any QC requirements in that message. "
                "Describe what to inspect — counts, alignment, or defects."
            ),
            action="info",
            sku=sku_summary(db, sku),
        )

    card = {
        "intake_id": intake.id,
        "sku_id": sku.id,
        "checkpoints": checkpoints,
        "questions": questions,
    }

    if questions:
        q_lines = "\n".join(f"• {q['question']}" for q in questions)
        return StudioChatResult(
            reply=(
                f"I extracted {len(checkpoints)} candidate detection point(s). "
                f"Before confirming I need a few details:\n{q_lines}"
            ),
            action="follow_up",
            sku=sku_summary(db, sku),
            intake_id=intake.id,
            confirmation_card=card,
            questions=questions,
        )

    return StudioChatResult(
        reply=(
            f"I extracted {len(checkpoints)} detection point(s). "
            f"Review and confirm the card to save them to the standard."
        ),
        action="extracted",
        sku=sku_summary(db, sku),
        intake_id=intake.id,
        confirmation_card=card,
    )


# ── Publish: signed L2 bundle (§5.6) ──────────────────────────────────────────


def _canonical(manifest: Dict[str, Any]) -> str:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_bundle_manifest(db: Session, sku: QCSkuItem, tenant_id: str) -> Dict[str, Any]:
    """Assemble the L2 bundle manifest from the active standard revision.

    Raises ValueError (fail-closed) if there is no active revision or the
    revision has no confirmed detection points — a bundle can never be signed
    over an empty or unconfirmed standard.
    """
    active = (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=sku.id, tenant_id=tenant_id, status="active")
        .order_by(QCSkuStandardRevision.revision_no.desc())
        .first()
    )
    if active is None:
        raise ValueError(
            "Cannot publish: this SKU has no active confirmed standard revision."
        )
    dps = (
        db.query(QCDetectionPoint)
        .filter_by(standard_revision_id=active.id, is_active=True)
        .order_by(QCDetectionPoint.sort_order)
        .all()
    )
    if not dps:
        raise ValueError(
            "Cannot publish: the active standard revision has no confirmed "
            "detection points."
        )

    manifest = {
        "manifest_version": "studio-bundle-v1",
        "level": "L2",
        "tenant_id": tenant_id,
        "sku": {
            "id": sku.id,
            "item_number": sku.item_number,
            "name": sku.name,
            "category": sku.category,
        },
        "standard_revision": {
            "id": active.id,
            "revision_no": active.revision_no,
            "confirmed_by": active.confirmed_by,
            "confirmed_at": active.confirmed_at.isoformat() if active.confirmed_at else None,
        },
        "detection_points": [
            {
                "point_code": dp.point_code,
                "label": dp.label,
                "description": dp.description,
                "method_hint": dp.method_hint,
                "expected_value": dp.expected_value,
                "pass_criteria": dp.pass_criteria,
                "severity": dp.severity,
                "sort_order": dp.sort_order,
                "regions": dp.regions_json or [],
            }
            for dp in dps
        ],
        "standard_photos": [
            {
                "id": p.id,
                "sha256": p.sha256,
                "mime_type": p.mime_type,
                "view_type": p.view_type,
                "angle": p.angle,
                "is_primary": p.is_primary,
            }
            for p in sku.photos
        ],
        "generated_at": _now().isoformat(),
    }
    return manifest


def sign_manifest(manifest: Dict[str, Any]) -> Dict[str, str]:
    """Sign the canonical manifest with the server Ed25519 key.

    Returns ``{bundle_hash, signature, signature_algorithm, signing_key_id}``.
    Ed25519 (not HMAC) is the single production bundle format so a deployed Pad
    verifies with a public key it can hold safely; see
    :mod:`src.qc_model.bundle.ed25519`.
    """
    canonical = _canonical(manifest).encode("utf-8")
    bundle_hash = hashlib.sha256(canonical).hexdigest()
    signer = _ed.load_signer()
    return {
        "bundle_hash": bundle_hash,
        "signature": signer.sign(canonical),
        "signature_algorithm": _ed.SIGNATURE_ALGO,
        "signing_key_id": signer.fingerprint,
    }


def verify_bundle(manifest: Dict[str, Any], signature: str) -> bool:
    """Verify an Ed25519 manifest signature with the verify-side public key."""
    canonical = _canonical(manifest).encode("utf-8")
    return _ed.verify_signature(_ed.load_public_key(), canonical, signature)


def build_publish_archive(db: Session, sku_id: str, tenant_id: str):
    """Build the canonical Ed25519-signed ``.tar.gz`` bundle for a SKU.

    Embeds the standard photos as payload files under ``photos/`` and signs the
    manifest + checksum. Fail-closed: raises ValueError if the SKU/standard is
    not publishable. Returns a :class:`ed25519.SignedArchive`.
    """
    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise ValueError("SKU not found.")
    manifest = build_bundle_manifest(db, sku, tenant_id)

    # Fail-closed on the payload: every photo the manifest declares must be
    # present on disk and match its recorded checksum. A bundle is never built
    # with a missing photo file (missing payload), a photo that carries no
    # recorded checksum to verify against (unverifiable payload), or a photo
    # whose bytes have drifted from the sha256 recorded at upload (stale payload).
    photos: List[tuple] = []
    for p in sku.photos:
        if not p.local_path or not Path(p.local_path).is_file():
            raise ValueError(
                f"Cannot publish: standard photo {p.id} file is missing "
                f"({p.local_path!r}). Re-upload it before publishing."
            )
        data = Path(p.local_path).read_bytes()
        if not p.sha256:
            raise ValueError(
                f"Cannot publish: standard photo {p.id} has no recorded sha256, so "
                f"its payload cannot be verified. Re-upload it before publishing."
            )
        if hashlib.sha256(data).hexdigest() != p.sha256:
            raise ValueError(
                f"Cannot publish: standard photo {p.id} on disk does not match "
                f"its recorded checksum (stale payload). Re-upload it before publishing."
            )
        photos.append((f"photos/{p.id}", data))
    return _ed.build_signed_archive(manifest, photos)


def publish_bundle(
    db: Session,
    sku_id: str,
    tenant_id: str,
    published_by: Optional[str] = None,
) -> QCPublishBundle:
    """Generate + persist a signed L2 bundle for a SKU (§5.6).

    Raises ValueError (fail-closed) if the standard is not publishable.
    """
    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise ValueError("SKU not found.")

    # Build the canonical signed .tar.gz first. This is the real publish gate:
    # it fail-closes when a declared standard photo file is missing or its bytes
    # have drifted from the recorded sha256, so a bundle is never persisted with
    # missing/stale photo payloads. We reuse its (validated) manifest.
    archive = build_publish_archive(db, sku_id, tenant_id)
    manifest = archive.manifest
    signed = sign_manifest(manifest)

    bundle_id = _uid()

    # Persist the canonical photo-carrying archive to disk *before* recording the
    # row, so the history row is never visible without its downloadable payload.
    # This is what a Pad actually imports; the DB row only carries the manifest +
    # manifest-level signature for the admin API.
    archive_path = _bundle_archive_path(tenant_id, bundle_id)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive.archive_bytes)

    bundle = QCPublishBundle(
        id=bundle_id,
        tenant_id=tenant_id,
        sku_id=sku.id,
        standard_revision_id=manifest["standard_revision"]["id"],
        revision_no=manifest["standard_revision"]["revision_no"],
        level="L2",
        manifest_version=manifest["manifest_version"],
        manifest_json=manifest,
        bundle_hash=signed["bundle_hash"],
        signature=signed["signature"],
        signature_algorithm=signed["signature_algorithm"],
        signing_key_id=signed["signing_key_id"],
        detection_point_count=len(manifest["detection_points"]),
        published_by=published_by,
        created_at=_now(),
    )
    db.add(bundle)
    db.commit()
    db.refresh(bundle)

    # Publishing a standard is exactly "newly installed" (PRD Authoring
    # Extension §3.2): it must run under mandatory human confirmation until it
    # qualifies solo. get_or_create so re-publishing the *same* revision (e.g.
    # a region-only edit, which does not mint a new standard_revision_id) never
    # resets progress -- only a genuinely new revision id gets a fresh record.
    _probation.start_probation(
        db, standard_revision_id=bundle.standard_revision_id, tenant_id=tenant_id, sku_id=sku.id,
    )

    return bundle


def download_publish_bundle(
    db: Session, tenant_id: str, bundle_id: str
) -> tuple[bytes, QCPublishBundle]:
    """Return the canonical signed ``.tar.gz`` for a published bundle, re-verified.

    Tenant-scoped and fail-closed: a bundle from another tenant is ``LookupError``
    (404); a missing on-disk payload or an archive that no longer verifies against
    the Ed25519 public key is a ``ValueError`` (409) and the bytes are never served.
    """
    bundle = (
        db.query(QCPublishBundle)
        .filter_by(id=bundle_id, tenant_id=tenant_id)
        .first()
    )
    if bundle is None:
        raise LookupError("Bundle not found.")

    path = _bundle_archive_path(tenant_id, bundle_id)
    if not path.is_file():
        raise ValueError(
            "Bundle archive payload is missing on disk; re-publish before download."
        )
    archive_bytes = path.read_bytes()
    try:
        # Re-verify the signed archive envelope (signature → checksums → manifest)
        # before serving. Never hand out a payload we cannot vouch for.
        _ed.verify_signed_archive(archive_bytes)
    except _ed.BundleVerifyError as exc:
        raise ValueError(f"Bundle failed verification: {exc}") from exc
    return archive_bytes, bundle


def bundle_view(bundle: QCPublishBundle) -> Dict[str, Any]:
    return {
        "id": bundle.id,
        "sku_id": bundle.sku_id,
        "standard_revision_id": bundle.standard_revision_id,
        "revision_no": bundle.revision_no,
        "level": bundle.level,
        "manifest_version": bundle.manifest_version,
        "bundle_hash": bundle.bundle_hash,
        "signature": bundle.signature,
        "signature_algorithm": bundle.signature_algorithm,
        "signing_key_id": bundle.signing_key_id,
        "detection_point_count": bundle.detection_point_count,
        "published_by": bundle.published_by,
        "created_at": bundle.created_at.isoformat() if bundle.created_at else None,
        "download_url": (
            f"/admin/studio/bundles/{bundle.id}/download"
            f"?tenant_id={quote(bundle.tenant_id, safe='')}"
        ),
    }
