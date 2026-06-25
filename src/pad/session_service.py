"""Operator session management for QC Pad."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.db.pad_models import QCConversationSession, QCOperatorProfile


def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return dk.hex()


def _make_password_hash(password: str) -> str:
    salt = os.urandom(16).hex()
    hashed = _hash_password(password, salt)
    return f"{salt}${hashed}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, hashed = stored_hash.split("$", 1)
    except ValueError:
        return False
    return _hash_password(password, salt) == hashed


_DEMO_OPERATORS = [
    {
        "username": "operator_cn",
        "display_name": "Chinese Operator",
        "role": "operator",
        "preferred_language": "zh-CN",
    },
    {
        "username": "operator_en",
        "display_name": "English Operator",
        "role": "operator",
        "preferred_language": "en",
    },
    {
        "username": "reviewer_ja",
        "display_name": "Japanese Reviewer",
        "role": "reviewer",
        "preferred_language": "ja",
    },
    {
        "username": "admin_en",
        "display_name": "Admin English",
        "role": "admin",
        "preferred_language": "en",
    },
]


def seed_demo_operators(db: Session, tenant_id: str = "demo") -> None:
    for demo in _DEMO_OPERATORS:
        exists = (
            db.query(QCOperatorProfile)
            .filter_by(tenant_id=tenant_id, username=demo["username"])
            .first()
        )
        if exists:
            continue
        profile = QCOperatorProfile(
            tenant_id=tenant_id,
            username=demo["username"],
            display_name=demo["display_name"],
            role=demo["role"],
            preferred_language=demo["preferred_language"],
            password_hash=_make_password_hash(demo["username"]),  # password == username
            is_active=True,
        )
        db.add(profile)
    db.commit()


def authenticate_operator(
    db: Session, username: str, password: str, tenant_id: str = "demo"
) -> Optional[QCOperatorProfile]:
    profile = (
        db.query(QCOperatorProfile)
        .filter_by(tenant_id=tenant_id, username=username, is_active=True)
        .first()
    )
    if profile is None:
        return None
    if not _verify_password(password, profile.password_hash):
        return None
    return profile


def get_operator_by_id(db: Session, operator_id: int) -> Optional[QCOperatorProfile]:
    return db.query(QCOperatorProfile).filter_by(id=operator_id).first()


def get_or_create_conversation_session(
    db: Session,
    operator_id: int,
    tenant_id: str,
    preferred_language: str,
) -> QCConversationSession:
    session = (
        db.query(QCConversationSession)
        .filter_by(operator_id=operator_id, tenant_id=tenant_id, status="active")
        .order_by(QCConversationSession.created_at.desc())
        .first()
    )
    if session is None:
        session = QCConversationSession(
            tenant_id=tenant_id,
            operator_id=operator_id,
            preferred_language=preferred_language,
            status="active",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def update_preferred_language(
    db: Session, operator_id: int, preferred_language: str
) -> Optional[QCOperatorProfile]:
    profile = db.query(QCOperatorProfile).filter_by(id=operator_id).first()
    if profile is None:
        return None
    profile.preferred_language = preferred_language
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return profile
