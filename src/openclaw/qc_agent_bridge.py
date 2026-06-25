"""OpenClaw LLM bridge for QC pad multilingual processing."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


_CHINESE_RE = re.compile(r'[一-鿿㐀-䶿]')
_JAPANESE_RE = re.compile(r'[぀-ゟ゠-ヿ]')

INTENT_THRESHOLD = 0.50
LOW_CONFIDENCE_THRESHOLD = 0.30


@dataclass
class CheckpointProposal:
    point_code: str
    label: str
    severity: str = "major"
    method_hint: Optional[str] = None
    expected_value: Optional[str] = None
    description: Optional[str] = None
    pass_criteria: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "point_code": self.point_code,
            "label": self.label,
            "severity": self.severity,
            "method_hint": self.method_hint,
            "expected_value": self.expected_value,
            "description": self.description or f"{self.label} checkpoint",
            "pass_criteria": self.pass_criteria or f"{self.label} must pass",
        }


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

    # Chinese patterns: (regex, point_code, label, severity, method_hint)
    _ZH_STANDARD_PATTERNS: List[Tuple] = [
        (r'纽扣\s*(\d+)\s*颗|(\d+)\s*颗.*?纽扣', "BUTTON_COUNT", "Button Count", "critical", "counting"),
        (r'领口.*?线迹|领口线迹|领口.*?缝线|领.*?不能歪', "COLLAR_STITCHING", "Collar Stitching", "major", "defect_detection"),
        (r'污渍|不能有污渍|面料.*?污渍|布面.*?污渍', "FABRIC_STAIN", "Fabric Stain", "major", "defect_detection"),
        (r'标签位置|标签.*?要对|标签.*?对齐|标牌位置', "LABEL_POSITION", "Label Position", "minor", "alignment"),
        (r'珍珠\s*(\d+)\s*颗|(\d+)\s*颗.*?珍珠', "PEARL_COUNT", "Pearl Count", "critical", "counting"),
        (r'水钻\s*(\d+)\s*颗|钻石\s*(\d+)\s*颗|水晶\s*(\d+)\s*颗', "RHINESTONE_COUNT", "Rhinestone Count", "critical", "counting"),
        (r'花瓣.*?完整|花瓣.*?不能破损|花瓣.*?无损', "PETAL_INTEGRITY", "Petal Integrity", "critical", "defect_detection"),
        (r'花蕊.*?居中|花芯.*?居中|花蕊.*?对中', "STAMEN_CENTERING", "Stamen Centering", "major", "alignment"),
    ]

    # English patterns: (regex, point_code, label, severity, method_hint)
    _EN_STANDARD_PATTERNS: List[Tuple] = [
        (r'(\d+)\s*buttons?', "BUTTON_COUNT", "Button Count", "critical", "counting"),
        (r'collar\s*stitch(?:ing)?', "COLLAR_STITCHING", "Collar Stitching", "major", "visual_inspection"),
        (r'(?:no\s+)?(?:fabric\s+)?stains?|fabric.*?clean', "FABRIC_STAIN", "Fabric Stain", "major", "visual_inspection"),
        (r'label\s*position|label\s*placement|label\s*correct', "LABEL_POSITION", "Label Position", "minor", "visual_inspection"),
        (r'(\d+)\s*pearls?', "PEARL_COUNT", "Pearl Count", "critical", "counting"),
        (r'(\d+)\s*rhinestones?|(\d+)\s*crystals?', "RHINESTONE_COUNT", "Rhinestone Count", "critical", "counting"),
        (r'petals?\s*(?:intact|complete|integrity|not\s*damaged)', "PETAL_INTEGRITY", "Petal Integrity", "critical", "visual_inspection"),
        (r'stamen\s*(?:center(?:ing|ed)?|align(?:ed)?)', "STAMEN_CENTERING", "Stamen Centering", "major", "alignment"),
    ]

    # Japanese patterns: (regex, point_code, label, severity, method_hint)
    _JA_STANDARD_PATTERNS: List[Tuple] = [
        (r'ボタン\s*(\d+)\s*個|(\d+)\s*個.*?ボタン', "BUTTON_COUNT", "Button Count", "critical", "counting"),
        (r'衿.*?縫い目|衿ステッチ|首.*?縫い目|衿.*?まっすぐ', "COLLAR_STITCHING", "Collar Stitching", "major", "defect_detection"),
        (r'生地.*?汚れ|布.*?汚れ|汚れ.*?なし|汚れ.*?ない', "FABRIC_STAIN", "Fabric Stain", "major", "defect_detection"),
        (r'ラベル.*?位置|タグ.*?位置|ラベル.*?正確|ラベル.*?正しい', "LABEL_POSITION", "Label Position", "minor", "alignment"),
        (r'真珠\s*(\d+)\s*個|(\d+)\s*個.*?真珠', "PEARL_COUNT", "Pearl Count", "critical", "counting"),
        (r'ラインストーン\s*(\d+)\s*個|水晶\s*(\d+)\s*個', "RHINESTONE_COUNT", "Rhinestone Count", "critical", "counting"),
        (r'花びら.*?完整|花びら.*?欠け.*?なし|ペタル.*?完全', "PETAL_INTEGRITY", "Petal Integrity", "critical", "defect_detection"),
        (r'雌しべ.*?中央|花芯.*?中央|中心.*?合わせ', "STAMEN_CENTERING", "Stamen Centering", "major", "alignment"),
    ]

    _INTENT_KEYWORDS: Dict[str, List[str]] = {
        "create_standard_intake": [
            "standard", "criteria", "requirement", "define standard",
            "検査基準", "品質基準", "基準定義",
        ],
        "update_standard_intake": [
            "update standard", "modify standard", "change checkpoint",
            "更新标准", "修改标准",
        ],
        "start_inspection": [
            "start", "begin", "inspect", "inspection", "开始", "検査",
        ],
        "submit_checkpoint": [
            "submit", "check", "pass", "fail", "result", "测量", "结果", "提交",
            "合格", "不合格", "提出", "結果",
        ],
        "view_report": [
            "report", "view", "show", "summary", "报告", "查看", "显示", "レポート", "表示",
        ],
        "get_report": [
            "get report", "fetch report", "获取报告", "レポート取得",
        ],
        "confirm_standard": [
            "confirm standard", "approve standard", "确认标准", "標準確認",
        ],
        "confirm_intake": [
            "confirm", "yes", "ok", "approve", "确认", "是", "好的", "確認", "はい",
        ],
        "reject_standard": [
            "reject standard", "reject", "cancel standard", "拒绝", "却下",
        ],
        "create_inspection_job": [
            "create job", "new inspection job", "start job",
        ],
        "attach_inspection_media": [
            "attach photo", "attach image", "upload photo", "add photo",
        ],
        "ingest_model_output": [
            "model result", "ai result", "qwen result", "model output",
        ],
        "finalize_inspection": [
            "finalize", "complete inspection", "finish inspection", "完成检查",
        ],
        "set_language": [
            "language", "lang", "chinese", "english", "japanese", "中文", "英文", "日本語",
        ],
        "ask_clarifying_question": [
            "what", "which", "how many", "clarify", "什么", "哪个", "多少",
        ],
        "unknown": [],
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
        "Standard intake detected — please confirm checkpoints": "已识别品质标准 — 请确认检查点",
    }

    _LOCALIZE_EN_TO_JA: Dict[str, str] = {
        "Inspection started": "検査を開始しました",
        "Please confirm": "確認してください",
        "Result submitted": "結果を提出しました",
        "Clarification needed": "明確化が必要です",
        "Language updated": "言語を更新しました",
        "Standard intake detected — please confirm checkpoints": "品質基準を検出しました — チェックポイントを確認してください",
    }

    def detect_language(self, text: str) -> str:
        # Hiragana/katakana are exclusively Japanese — check before CJK
        if _JAPANESE_RE.search(text):
            return "ja"
        if _CHINESE_RE.search(text):
            return "zh-CN"
        return "en"

    def detect_standard_pattern(
        self, raw_text: str, lang: str
    ) -> Tuple[bool, List[CheckpointProposal], str]:
        """Detect if raw_text defines QC inspection standards (≥2 checkpoints).

        Returns (is_standard, checkpoints, canonical_english_text).
        """
        if lang == "zh-CN":
            patterns = self._ZH_STANDARD_PATTERNS
        elif lang == "ja":
            patterns = self._JA_STANDARD_PATTERNS
        elif lang == "en":
            patterns = self._EN_STANDARD_PATTERNS
        else:
            return False, [], raw_text

        found: List[CheckpointProposal] = []
        seen_codes: set = set()

        for pattern, code, label, severity, method in patterns:
            if code in seen_codes:
                continue
            m = re.search(pattern, raw_text)
            if m:
                expected_value: Optional[str] = None
                if m.lastindex:
                    for g in range(1, m.lastindex + 1):
                        val = m.group(g)
                        if val is not None:
                            expected_value = val
                            break
                found.append(CheckpointProposal(
                    point_code=code,
                    label=label,
                    severity=severity,
                    method_hint=method,
                    expected_value=expected_value,
                    description=f"{label} inspection checkpoint",
                    pass_criteria=f"{label} must pass",
                ))
                seen_codes.add(code)

        if len(found) >= 2:
            parts = []
            for cp in found:
                if cp.expected_value:
                    parts.append(f"{cp.label.lower()} {cp.expected_value}")
                else:
                    parts.append(f"{cp.label.lower()} check")
            canonical_en = "QC standard: " + ", ".join(parts)
            return True, found, canonical_en

        return False, found, ""

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

    def classify_intent(self, text_en: str) -> Tuple[str, float]:
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
            point_code="VISUAL_INSPECTION",
            label="Visual Inspection",
            severity="major",
            method_hint="defect_detection",
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
        if _JAPANESE_RE.search(text):
            return "ja"
        if _CHINESE_RE.search(text):
            return "zh-CN"
        return "en"

    def detect_standard_pattern(
        self, raw_text: str, lang: str
    ) -> Tuple[bool, List[CheckpointProposal], str]:
        raise NotImplementedError("RealOpenClawLLMClient not wired up")

    def translate_to_english(self, text: str, source_lang: str) -> str:
        raise NotImplementedError("RealOpenClawLLMClient not wired up")

    def classify_intent(self, text_en: str) -> Tuple[str, float]:
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

    def classify_qc_intent(self, text_en: str) -> Tuple[str, float]:
        return self._client.classify_intent(text_en)

    def extract_qc_checkpoints(self, text_en: str, intent: str) -> List[CheckpointProposal]:
        return self._client.extract_checkpoints(text_en, intent)

    def localize_response(self, text_en: str, target_lang: str) -> str:
        return self._client.localize(text_en, target_lang)

    def process(self, raw_text: str, preferred_language: str = "en") -> OpenClawResponse:
        detected_lang = self.detect_language(raw_text)

        # Standard pattern detection runs BEFORE keyword classification.
        # Chinese/Japanese standard definitions (≥2 checkpoint patterns) are
        # recognized here rather than relying on word-by-word translation.
        is_standard, std_checkpoints, canonical_en = self._client.detect_standard_pattern(
            raw_text, detected_lang
        )
        if is_standard:
            reply_en = "Standard intake detected — please confirm checkpoints"
            localized = self.localize_response(reply_en, preferred_language)
            return OpenClawResponse(
                detected_language=detected_lang,
                normalized_text_en=canonical_en,
                intent="create_standard_intake",
                confidence=0.85,
                checkpoints=std_checkpoints,
                localized_reply=localized,
                action_data={"intent": "create_standard_intake", "confidence": 0.85},
            )

        # Regular keyword-based processing for non-standard messages
        normalized_en = self.translate_text(raw_text, detected_lang)
        intent, confidence = self.classify_qc_intent(normalized_en)
        checkpoints = self.extract_qc_checkpoints(normalized_en, intent)
        reply_en = (
            "Clarification needed"
            if confidence < INTENT_THRESHOLD
            else intent.replace("_", " ").capitalize()
        )
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
