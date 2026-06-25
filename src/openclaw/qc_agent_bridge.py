"""OpenClaw LLM bridge for QC pad multilingual processing."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_CHINESE_RE = re.compile(r'[一-鿿㐀-䶿]')
_JAPANESE_RE = re.compile(r'[぀-ゟ゠-ヿ]')

INTENT_THRESHOLD = 0.50
LOW_CONFIDENCE_THRESHOLD = 0.30


@dataclass
class CheckpointProposal:
    checkpoint_name: str
    expected_value: str
    unit: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class OpenClawResponse:
    detected_language: str
    normalized_text_en: str
    intent: str
    confidence: float
    checkpoints: List[CheckpointProposal] = field(default_factory=list)
    localized_reply: str = ""
    action_data: Dict[str, Any] = field(default_factory=dict)


class FakeOpenClawLLMClient:
    """Deterministic fake for CI/tests — no network calls."""

    _INTENT_KEYWORDS: Dict[str, List[str]] = {
        "start_inspection": [
            "start", "begin", "inspect", "inspection", "开始", "检查", "检验", "開始", "検査",
        ],
        "submit_checkpoint": [
            "submit", "check", "pass", "fail", "result", "测量", "结果", "提交", "测试",
            "合格", "不合格", "提出", "結果",
        ],
        "view_report": [
            "report", "view", "show", "summary", "报告", "查看", "显示", "レポート", "表示",
        ],
        "confirm_intake": [
            "confirm", "yes", "ok", "approve", "确认", "是", "好的", "確認", "はい",
        ],
        "set_language": [
            "language", "lang", "chinese", "english", "japanese", "中文", "英文", "日本語",
        ],
    }

    _ZH_TRANSLATIONS: Dict[str, str] = {
        "开始检查": "start inspection",
        "检验": "inspect",
        "检查": "check",
        "开始": "start",
        "结果": "result",
        "报告": "report",
        "确认": "confirm",
        "提交": "submit",
    }

    _JA_TRANSLATIONS: Dict[str, str] = {
        "検査開始": "start inspection",
        "検査": "inspect",
        "結果": "result",
        "レポート": "report",
        "確認": "confirm",
        "提出": "submit",
    }

    _LOCALIZE_EN_TO_ZH: Dict[str, str] = {
        "Inspection started": "检查已开始",
        "Please confirm": "请确认",
        "Result submitted": "结果已提交",
        "Clarification needed": "需要澄清",
        "Language updated": "语言已更新",
    }

    _LOCALIZE_EN_TO_JA: Dict[str, str] = {
        "Inspection started": "検査を開始しました",
        "Please confirm": "確認してください",
        "Result submitted": "結果を提出しました",
        "Clarification needed": "明確化が必要です",
        "Language updated": "言語を更新しました",
    }

    def detect_language(self, text: str) -> str:
        # Hiragana/katakana are exclusively Japanese — check before CJK
        if _JAPANESE_RE.search(text):
            return "ja"
        if _CHINESE_RE.search(text):
            return "zh-CN"
        return "en"

    def translate_to_english(self, text: str, source_lang: str) -> str:
        if source_lang == "zh-CN":
            result = text
            for zh, en in self._ZH_TRANSLATIONS.items():
                result = result.replace(zh, en)
            return result
        if source_lang == "ja":
            result = text
            for ja, en in self._JA_TRANSLATIONS.items():
                result = result.replace(ja, en)
            return result
        return text

    def classify_intent(self, text_en: str) -> tuple[str, float]:
        text_lower = text_en.lower()
        best_intent = "unknown"
        best_score = LOW_CONFIDENCE_THRESHOLD
        for intent, keywords in self._INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower or kw in text_en:
                    best_intent = intent
                    best_score = 0.85
                    break
            if best_score >= INTENT_THRESHOLD:
                break
        return best_intent, best_score

    def extract_checkpoints(self, text_en: str, intent: str) -> List[CheckpointProposal]:
        if intent not in ("submit_checkpoint", "start_inspection"):
            return []
        return [CheckpointProposal(
            checkpoint_name="visual_inspection",
            expected_value="pass",
        )]

    def localize(self, text_en: str, target_lang: str) -> str:
        if target_lang == "zh-CN":
            return self._LOCALIZE_EN_TO_ZH.get(text_en, text_en)
        if target_lang == "ja":
            return self._LOCALIZE_EN_TO_JA.get(text_en, text_en)
        return text_en


class RealOpenClawLLMClient:
    """Production client — activated when OPENCLAW_API_URL is set."""

    def __init__(self, api_url: str, api_key: str = ""):
        self._api_url = api_url
        self._api_key = api_key

    def detect_language(self, text: str) -> str:
        # Placeholder: real implementation calls remote service
        if _JAPANESE_RE.search(text):
            return "ja"
        if _CHINESE_RE.search(text):
            return "zh-CN"
        return "en"

    def translate_to_english(self, text: str, source_lang: str) -> str:
        raise NotImplementedError("RealOpenClawLLMClient not wired up")

    def classify_intent(self, text_en: str) -> tuple[str, float]:
        raise NotImplementedError("RealOpenClawLLMClient not wired up")

    def extract_checkpoints(self, text_en: str, intent: str) -> List[CheckpointProposal]:
        raise NotImplementedError("RealOpenClawLLMClient not wired up")

    def localize(self, text_en: str, target_lang: str) -> str:
        raise NotImplementedError("RealOpenClawLLMClient not wired up")


def _build_client():
    api_url = os.getenv("OPENCLAW_API_URL", "")
    if api_url:
        return RealOpenClawLLMClient(api_url, os.getenv("OPENCLAW_API_KEY", ""))
    return FakeOpenClawLLMClient()


class QCAgentBridge:
    """Orchestrates the detect→translate→classify→extract→localize pipeline."""

    def __init__(self, client=None):
        self._client = client or _build_client()

    def detect_language(self, text: str) -> str:
        return self._client.detect_language(text)

    def translate_text(self, text: str, source_lang: str) -> str:
        if source_lang == "en":
            return text
        return self._client.translate_to_english(text, source_lang)

    def classify_qc_intent(self, text_en: str) -> tuple[str, float]:
        return self._client.classify_intent(text_en)

    def extract_qc_checkpoints(self, text_en: str, intent: str) -> List[CheckpointProposal]:
        return self._client.extract_checkpoints(text_en, intent)

    def localize_response(self, text_en: str, target_lang: str) -> str:
        return self._client.localize(text_en, target_lang)

    def process(self, raw_text: str, preferred_language: str = "en") -> OpenClawResponse:
        detected_lang = self.detect_language(raw_text)
        normalized_en = self.translate_text(raw_text, detected_lang)
        intent, confidence = self.classify_qc_intent(normalized_en)
        checkpoints = self.extract_qc_checkpoints(normalized_en, intent)
        reply_en = "Clarification needed" if confidence < INTENT_THRESHOLD else intent.replace("_", " ").capitalize()
        localized = self.localize_response(reply_en, preferred_language)
        return OpenClawResponse(
            detected_language=detected_lang,
            normalized_text_en=normalized_en,
            intent=intent,
            confidence=confidence,
            checkpoints=checkpoints,
            localized_reply=localized,
            action_data={"intent": intent, "confidence": confidence},
        )


_bridge_singleton: Optional[QCAgentBridge] = None


def get_bridge() -> QCAgentBridge:
    global _bridge_singleton
    if _bridge_singleton is None:
        _bridge_singleton = QCAgentBridge()
    return _bridge_singleton
