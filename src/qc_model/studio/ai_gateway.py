"""Provider-neutral AI gateway for the Admin Studio authoring conversation.

The product talks in terms of a text assistant and a vision assistant.  Their
currently configured implementations are deployment details supplied through
environment variables; no provider or model is a product dependency.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class StudioAIError(RuntimeError):
    """A configured authoring model could not produce a safe structured result."""


@dataclass(frozen=True)
class AssistantConfig:
    role: str
    provider: str
    base_url: str
    model: str
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)


def text_config() -> AssistantConfig:
    return AssistantConfig(
        role="text",
        provider=os.getenv("STUDIO_TEXT_PROVIDER", "ollama_compatible").strip(),
        base_url=os.getenv("STUDIO_TEXT_BASE_URL", "").strip().rstrip("/"),
        model=os.getenv("STUDIO_TEXT_MODEL", "").strip(),
        timeout_seconds=float(os.getenv("STUDIO_AI_TIMEOUT_SECONDS", "90")),
    )


def vision_config() -> AssistantConfig:
    return AssistantConfig(
        role="vision",
        provider=os.getenv("STUDIO_VISION_PROVIDER", "openai_compatible").strip(),
        base_url=os.getenv("STUDIO_VISION_BASE_URL", "").strip().rstrip("/"),
        model=os.getenv("STUDIO_VISION_MODEL", "").strip(),
        timeout_seconds=float(os.getenv("STUDIO_AI_TIMEOUT_SECONDS", "90")),
    )


_CHECKPOINT_EXAMPLE = {
    "point_code": "UPPERCASE_CODE",
    "label": "short localized label",
    "description": "what must be inspected",
    "method_hint": "counting|alignment|defect_detection|presence_check|shape_compare|readability_check",
    "severity": "minor|major|critical",
    "expected_value": "exact value or null",
    "pass_criteria": "specific pass criterion",
}


def _locale_name(language: str) -> str:
    return {"zh-CN": "Simplified Chinese", "ja": "Japanese"}.get(language, "English")


def _clean_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        raise StudioAIError("assistant_response_not_json")
    try:
        # Decode the first complete object.  Small local VLMs sometimes emit
        # an otherwise valid object followed by one redundant brace or a
        # short acknowledgement.  Accepting that suffix is safe because the
        # decoded object is still validated field by field below; incomplete
        # or internally malformed JSON continues to fail closed.
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise StudioAIError("assistant_response_invalid_json") from exc
    if not isinstance(value, dict):
        raise StudioAIError("assistant_response_not_object")
    return value


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(item.get("text") or "") for item in value if isinstance(item, dict)
        )
    raise StudioAIError("assistant_content_not_text")


def _validate_checkpoint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StudioAIError("assistant_checkpoint_not_object")
    point_code = str(value.get("point_code") or "").strip().upper()
    label = str(value.get("label") or "").strip()
    if not point_code or not label:
        raise StudioAIError("assistant_checkpoint_missing_identity")
    method = str(value.get("method_hint") or "defect_detection").strip()
    if method not in {
        "counting", "alignment", "defect_detection", "presence_check",
        "shape_compare", "readability_check",
    }:
        method = "defect_detection"
    severity = str(value.get("severity") or "major").strip()
    if severity not in {"minor", "major", "critical"}:
        severity = "major"
    expected = value.get("expected_value")
    if expected is not None:
        expected = str(expected).strip() or None
    checkpoint = {
        "point_code": re.sub(r"[^A-Z0-9_]+", "_", point_code)[:64],
        "label": label[:256],
        "description": str(value.get("description") or "").strip()[:2000] or None,
        "method_hint": method,
        "severity": severity,
        "expected_value": expected,
        "pass_criteria": str(value.get("pass_criteria") or "").strip()[:2000] or None,
    }
    if not checkpoint["expected_value"]:
        # Normalize an explicit bound that the assistant already placed in the
        # description/criterion. This is not inference: both number and unit
        # must be present, otherwise the value remains unknown.
        evidence = " ".join(filter(None, (
            checkpoint["description"], checkpoint["pass_criteria"],
        )))
        bound = re.search(
            r"(?:≤|<=|不超过|不得超过|最多|maximum|max(?:imum)?\s*(?:of)?|within)\s*"
            r"(\d+(?:\.\d+)?)\s*(毫米|厘米|mm|cm|μm|um|度|°|%|个|件)",
            evidence,
            flags=re.IGNORECASE,
        )
        if bound:
            units = {"毫米": "mm", "厘米": "cm", "个": "pcs", "件": "pcs"}
            unit = units.get(bound.group(2).lower(), bound.group(2))
            checkpoint["expected_value"] = f"≤{bound.group(1)} {unit}"
    return checkpoint


def _normalize_result(
    value: dict[str, Any],
    config: AssistantConfig,
    elapsed_ms: int,
    language: str,
) -> dict[str, Any]:
    intent = str(value.get("intent") or "define_requirements").strip()
    if intent not in {"create_sku", "define_requirements", "provide_details", "select_sku", "help"}:
        intent = "define_requirements"
    reply = str(value.get("reply") or "").strip()
    if not reply:
        reply = {
            "zh-CN": "我已生成质检标准草案，请审核候选检测点并补充缺失信息。",
            "ja": "検査標準の草案を作成しました。候補項目を確認し、不足情報を補ってください。",
        }.get(language, "I drafted the QC standard. Review the candidate points and provide any missing details.")
    raw_sku = value.get("sku") if isinstance(value.get("sku"), dict) else {}
    sku = {
        "item_number": str(raw_sku.get("item_number") or "").strip()[:128],
        "name": str(raw_sku.get("name") or "").strip()[:256],
        "category": str(raw_sku.get("category") or "").strip()[:128] or None,
    }
    checkpoints = [_validate_checkpoint(item) for item in (value.get("checkpoints") or [])]
    questions = []
    for item in value.get("questions") or value.get("questions_for_operator") or []:
        if isinstance(item, str):
            question = item.strip()
            field = "standard"
        elif isinstance(item, dict):
            question = str(item.get("question") or "").strip()
            field = str(item.get("field") or "standard").strip()
        else:
            continue
        if question:
            questions.append({"field": field[:128], "question": question[:1000]})
    for checkpoint in checkpoints:
        if checkpoint["method_hint"] == "counting" and not checkpoint["expected_value"]:
            field = f"{checkpoint['point_code']}.expected_value"
            if not any(q["field"] == field for q in questions):
                questions.append({
                    "field": field,
                    "question": f"Please provide the exact expected count for {checkpoint['label']}.",
                })
    # If an explicit value and unit were recovered from the same candidate,
    # discard model questions that redundantly ask for that field or unit.
    resolved = [cp for cp in checkpoints if cp["expected_value"]]
    if resolved:
        questions = [q for q in questions if not any(
            q["field"].upper().startswith(cp["point_code"])
            or cp["point_code"] in q["question"].upper()
            or cp["label"].lower() in q["question"].lower()
            for cp in resolved
        )]
    return {
        "intent": intent,
        "reply": reply[:6000],
        "sku": sku,
        "checkpoints": checkpoints,
        "questions": questions,
        "assistant": {
            "role": config.role,
            "provider": config.provider,
            "model": config.model,
            "elapsed_ms": elapsed_ms,
            "mode": "live",
        },
    }


def _post(config: AssistantConfig, payload: dict[str, Any], path: str) -> tuple[dict[str, Any], int]:
    if not config.configured:
        raise StudioAIError(f"{config.role}_assistant_not_configured")
    started = time.monotonic()
    try:
        with httpx.Client(timeout=config.timeout_seconds, limits=httpx.Limits(max_keepalive_connections=0)) as client:
            response = client.post(config.base_url + path, json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.TimeoutException as exc:
        raise StudioAIError(f"{config.role}_assistant_timeout") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise StudioAIError(f"{config.role}_assistant_unavailable") from exc
    return body, int((time.monotonic() - started) * 1000)


def author_text(*, message: str, language: str, current_sku: dict[str, Any] | None) -> dict[str, Any]:
    config = text_config()
    schema = {
        "intent": "create_sku|define_requirements|provide_details|select_sku|help",
        "reply": f"answer in {_locale_name(language)}",
        "sku": {"item_number": "required for create_sku", "name": "required for create_sku", "category": None},
        "checkpoints": [_CHECKPOINT_EXAMPLE],
        "questions": [{"field": "checkpoint field", "question": "one precise missing-information question"}],
    }
    system = (
        "You are Giraffe QC's provider-neutral standard-authoring assistant. "
        "Turn an administrator's natural-language request into safe structured data. "
        "Never claim that a draft is confirmed, published, installed, or inspecting; those require explicit human actions. "
        "Never guess counts, tolerances, units, or pass thresholds: use null and ask a precise question. "
        "For create_sku, return both item_number and name. For requirements, return every independently testable checkpoint. "
        "Return exactly one JSON object, with no markdown. Required schema: "
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
    context = json.dumps(current_sku or {}, ensure_ascii=False, separators=(",", ":"))
    if config.provider == "ollama_compatible":
        payload = {
            "model": config.model,
            "stream": False,
            "think": False,
            "format": "json",
            # CPU-only compatible deployments must have a hard output bound;
            # otherwise a malformed turn can continue generating long after
            # the browser has timed out.
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": 512},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Current SKU JSON: {context}\nAdministrator: {message}"},
            ],
        }
        body, elapsed = _post(config, payload, "/api/chat")
        try:
            raw = _content_text(body["message"]["content"])
        except (KeyError, TypeError) as exc:
            raise StudioAIError("text_assistant_envelope_invalid") from exc
    else:
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Current SKU JSON: {context}\nAdministrator: {message}"},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        body, elapsed = _post(config, payload, "/v1/chat/completions")
        try:
            raw = _content_text(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise StudioAIError("text_assistant_envelope_invalid") from exc
    return _normalize_result(_clean_json(str(raw)), config, elapsed, language)


def author_image(*, image_path: Path, mime_type: str, language: str, current_sku: dict[str, Any]) -> dict[str, Any]:
    config = vision_config()
    mime = mime_type or mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
    schema = {
        "intent": "define_requirements",
        "reply": f"visible-evidence summary in {_locale_name(language)}",
        "sku": {},
        "checkpoints": [_CHECKPOINT_EXAMPLE],
        "questions": [{"field": "standard", "question": "information that cannot be established from the image"}],
    }
    prompt = (
        "You are the vision assistant for Giraffe QC standard authoring. Analyze this reference photo only. "
        "Propose at most 3 high-value, visible, independently testable inspection checkpoints. "
        "Keep every label, description, pass criterion, and question concise. Do not infer hidden material properties, "
        "exact dimensions, tolerances, counts obscured by the view, or business rules. Ask for any missing facts. "
        "Use only method_hint values listed in the schema. This is only a candidate draft and must never be described "
        "as confirmed. Return one complete, valid JSON object only, with no markdown or trailing text: "
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        + "\nCurrent SKU: "
        + json.dumps(current_sku, ensure_ascii=False, separators=(",", ":"))
    )
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]}],
        "temperature": 0,
        "max_tokens": 768,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    body, elapsed = _post(config, payload, "/v1/chat/completions")
    try:
        raw = _content_text(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise StudioAIError("vision_assistant_envelope_invalid") from exc
    return _normalize_result(_clean_json(str(raw)), config, elapsed, language)


def assistant_status() -> dict[str, Any]:
    """Return configuration state without exposing internal endpoints."""
    def view(config: AssistantConfig) -> dict[str, Any]:
        return {
            "role": config.role,
            "configured": config.configured,
            "provider": config.provider if config.configured else None,
            "model": config.model if config.configured else None,
        }
    return {"text": view(text_config()), "vision": view(vision_config())}
