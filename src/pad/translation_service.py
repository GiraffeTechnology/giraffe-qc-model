"""Thin wrapper around QCAgentBridge for translation operations."""
from __future__ import annotations

from src.openclaw.qc_agent_bridge import OpenClawResponse, QCAgentBridge, get_bridge


def process_text(
    raw_text: str,
    preferred_language: str = "en",
    bridge: QCAgentBridge | None = None,
) -> OpenClawResponse:
    b = bridge or get_bridge()
    return b.process(raw_text, preferred_language)


def detect_language(raw_text: str, bridge: QCAgentBridge | None = None) -> str:
    b = bridge or get_bridge()
    return b.detect_language(raw_text)


def localize(text_en: str, target_lang: str, bridge: QCAgentBridge | None = None) -> str:
    b = bridge or get_bridge()
    return b.localize_response(text_en, target_lang)
