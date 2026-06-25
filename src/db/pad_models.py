from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from src.db.base import Base


class QCOperatorProfile(Base):
    __tablename__ = "qc_operator_profiles"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    username = Column(String(128), nullable=False)
    display_name = Column(String(256), nullable=True)
    role = Column(String(64), nullable=False, default="operator")
    preferred_language = Column(String(16), nullable=False, default="en")
    password_hash = Column(String(512), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_operator_tenant_username"),
    )

    sessions = relationship("QCConversationSession", back_populates="operator")
    messages = relationship("QCConversationMessage", back_populates="operator")


class QCConversationSession(Base):
    __tablename__ = "qc_conversation_sessions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    operator_id = Column(Integer, ForeignKey("qc_operator_profiles.id"), nullable=False)
    preferred_language = Column(String(16), nullable=False, default="en")
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    operator = relationship("QCOperatorProfile", back_populates="sessions")
    messages = relationship("QCConversationMessage", back_populates="session")


class QCConversationMessage(Base):
    __tablename__ = "qc_conversation_messages"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    session_id = Column(Integer, ForeignKey("qc_conversation_sessions.id"), nullable=False)
    operator_id = Column(Integer, ForeignKey("qc_operator_profiles.id"), nullable=False)
    role = Column(String(16), nullable=False)  # 'user' | 'assistant'
    source_language = Column(String(16), nullable=True)
    preferred_language = Column(String(16), nullable=True)
    raw_text_original = Column(Text, nullable=True)
    normalized_text_en = Column(Text, nullable=True)
    translated_output_text = Column(Text, nullable=True)
    intent = Column(String(64), nullable=True)
    confidence_score = Column(Float, nullable=True)
    action_json = Column(Text, nullable=True)
    linked_intake_id = Column(Integer, nullable=True)
    linked_job_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    session = relationship("QCConversationSession", back_populates="messages")
    operator = relationship("QCOperatorProfile", back_populates="messages")
