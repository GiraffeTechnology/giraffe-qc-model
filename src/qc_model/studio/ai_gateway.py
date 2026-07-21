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

from src.cv_preanalysis import build_prompt_block


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
        timeout_seconds=float(os.getenv(
            "STUDIO_VISION_TIMEOUT_SECONDS",
            os.getenv("STUDIO_AI_TIMEOUT_SECONDS", "90"),
        )),
    )


def vision_fallback_config() -> AssistantConfig:
    """Optional escalation model; absence means primary-only operation."""
    return AssistantConfig(
        role="vision",
        provider=os.getenv("STUDIO_VISION_FALLBACK_PROVIDER", "openai_compatible").strip(),
        base_url=os.getenv("STUDIO_VISION_FALLBACK_BASE_URL", "").strip().rstrip("/"),
        model=os.getenv("STUDIO_VISION_FALLBACK_MODEL", "").strip(),
        timeout_seconds=float(os.getenv(
            "STUDIO_VISION_FALLBACK_TIMEOUT_SECONDS",
            os.getenv("STUDIO_AI_TIMEOUT_SECONDS", "90"),
        )),
    )


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _escalation_confidence() -> float:
    try:
        return max(0.0, min(1.0, float(os.getenv(
            "STUDIO_VISION_ESCALATION_CONFIDENCE", "0.75"
        ))))
    except ValueError:
        return 0.75


_CHECKPOINT_EXAMPLE = {
    "point_code": "UPPERCASE_CODE",
    "label": "short localized label",
    "description": "what must be inspected",
    "method_hint": "counting|alignment|defect_detection|presence_check|shape_compare|readability_check",
    "severity": "minor|major|critical",
    "expected_value": "exact value or null",
    "pass_criteria": "specific pass criterion",
    "expected_features": {},
    "cv_config": {
        "analyzers": [{
            "name": "rhinestone_count|petal_segmentation|pistil_localization",
            "params": {},
        }],
    },
}

_ALLOWED_CV_ANALYZERS = frozenset({
    "rhinestone_count", "petal_segmentation", "pistil_localization",
})


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
        "expected_features": {},
        "cv_config": {},
    }
    expected_features = value.get("expected_features")
    if isinstance(expected_features, dict):
        checkpoint["expected_features"] = expected_features
    raw_cv_config = value.get("cv_config")
    if isinstance(raw_cv_config, dict) and isinstance(raw_cv_config.get("analyzers"), list):
        analyzers = []
        seen: set[str] = set()
        for item in raw_cv_config["analyzers"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            params = item.get("params", {})
            if name not in _ALLOWED_CV_ANALYZERS or name in seen or not isinstance(params, dict):
                continue
            seen.add(name)
            analyzers.append({"name": name, "params": params})
        if analyzers:
            checkpoint["cv_config"] = {"analyzers": analyzers}
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
    coverage_review = None
    raw_coverage = value.get("coverage_review")
    if isinstance(raw_coverage, dict):
        complete_raw = raw_coverage.get("complete")
        complete = complete_raw is True or str(complete_raw).strip().lower() == "true"
        checked = [
            str(item).strip()[:128]
            for item in (raw_coverage.get("checked_dimensions") or [])
            if str(item).strip()
        ][:16]
        omissions = [
            str(item).strip()[:500]
            for item in (raw_coverage.get("omissions") or [])
            if str(item).strip()
        ][:16]
        coverage_review = {
            "complete": complete,
            "checked_dimensions": checked,
            "omissions": omissions,
        }
    return {
        "intent": intent,
        "reply": reply[:6000],
        "sku": sku,
        "checkpoints": checkpoints,
        "questions": questions,
        "coverage_review": coverage_review,
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


def _vision_json(
    config: AssistantConfig,
    *,
    data_url: str | list[str],
    prompt: str,
    max_tokens: int,
) -> tuple[dict[str, Any], int]:
    image_urls = data_url if isinstance(data_url, list) else [data_url]
    content = [
        {"type": "image_url", "image_url": {"url": url}} for url in image_urls
    ]
    content.append({"type": "text", "text": prompt})
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    body, elapsed = _post(config, payload, "/v1/chat/completions")
    try:
        raw = _content_text(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise StudioAIError("vision_assistant_envelope_invalid") from exc
    return _clean_json(str(raw)), elapsed


def extract_image_text(
    *, image_path: Path, mime_type: str, language: str,
) -> dict[str, Any]:
    """Recover visible process-card text without applying QC judgment."""
    primary = vision_config()
    fallback = vision_fallback_config()
    mime = mime_type or mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
    schema = {
        "text": "all visible process-card text in reading order",
        "language": f"detected language; response metadata in {_locale_name(language)}",
        "layout_notes": "brief table/section layout notes or null",
    }
    prompt = (
        "Transcribe the visible process card exactly enough for QC standard authoring. "
        "Preserve numbers, units, tolerances, row order, headings, and labels. Do not infer "
        "or repair text that is not legible. Return one JSON object only: "
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
    selected = primary
    fallback_used = False
    reasons: list[str] = []
    try:
        value, elapsed = _vision_json(
            primary, data_url=data_url, prompt=prompt, max_tokens=2048,
        )
    except StudioAIError:
        if not (_env_enabled("STUDIO_VISION_FALLBACK_ENABLED", True) and fallback.configured):
            raise
        reasons.append("primary_ocr_error")
        value, elapsed = _vision_json(
            fallback, data_url=data_url, prompt=prompt, max_tokens=2048,
        )
        selected = fallback
        fallback_used = True
    text = str(value.get("text") or "").strip()
    if not text:
        raise StudioAIError("vision_ocr_no_readable_text")
    return {
        "text": text[:2_000_000],
        "language": str(value.get("language") or "").strip()[:64] or None,
        "layout_notes": str(value.get("layout_notes") or "").strip()[:2000] or None,
        "assistant": _assistant_route(
            selected=selected, elapsed_ms=elapsed, primary=primary, fallback=fallback,
            fallback_used=fallback_used, reasons=reasons,
        ),
    }


def _assistant_route(
    *,
    selected: AssistantConfig,
    elapsed_ms: int,
    primary: AssistantConfig,
    fallback: AssistantConfig,
    fallback_used: bool,
    reasons: list[str],
    passes: int = 1,
) -> dict[str, Any]:
    return {
        "role": "vision",
        "provider": selected.provider,
        "model": selected.model,
        "elapsed_ms": elapsed_ms,
        "mode": "live",
        "route": "fallback" if fallback_used else "primary",
        "strategy": "cv_then_primary_then_conditional_fallback",
        "primary_model": primary.model,
        "fallback_model": fallback.model if fallback.configured else None,
        "fallback_used": fallback_used,
        "escalation_reasons": reasons,
        "passes": passes,
    }


def _merge_authoring_results(
    first: dict[str, Any], reviewed: dict[str, Any],
) -> dict[str, Any]:
    """Keep reviewed points while never dropping a valid first-pass point."""
    merged = dict(reviewed)
    points = list(reviewed.get("checkpoints") or [])
    codes = {point["point_code"] for point in points}
    points.extend(
        point for point in first.get("checkpoints") or [] if point["point_code"] not in codes
    )
    merged["checkpoints"] = points
    questions = list(reviewed.get("questions") or [])
    seen = {(q["field"], q["question"]) for q in questions}
    questions.extend(
        q for q in first.get("questions") or []
        if (q["field"], q["question"]) not in seen
    )
    merged["questions"] = questions
    return merged


def author_image(*, image_path: Path, mime_type: str, language: str, current_sku: dict[str, Any]) -> dict[str, Any]:
    primary = vision_config()
    fallback = vision_fallback_config()
    mime = mime_type or mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
    schema = {
        "intent": "define_requirements",
        "reply": f"visible-evidence summary in {_locale_name(language)}",
        "sku": {},
        "checkpoints": [_CHECKPOINT_EXAMPLE],
        "questions": [{"field": "standard", "question": "information that cannot be established from the image"}],
        "coverage_review": {
            "complete": "true only after checking all visible quality dimensions",
            "checked_dimensions": [
                "components/count", "presence/completeness", "alignment/centering/symmetry",
                "shape", "surface/defects", "color/finish", "assembly", "readability",
            ],
            "omissions": [],
        },
    }
    prompt = (
        "You are the vision assistant for Giraffe QC standard authoring. Analyze this reference photo only. "
        "Produce a comprehensive but concise set of 3 to 8 high-value, visible, independently testable inspection checkpoints. "
        "Before returning, audit the whole visible object for components and counts, presence and completeness, "
        "relative alignment/centering/symmetry, shape, surface defects, color/finish, assembly, and readability. "
        "Do not stop at superficial defects and do not wait for the administrator to identify obvious omissions. "
        "Keep the reply to one sentence and every label, description, pass criterion, and question under 20 words. "
        "Do not infer hidden material properties, "
        "exact dimensions, tolerances, counts obscured by the view, or business rules. Ask for any missing facts. "
        "Only attach a cv_config analyzer when its analyzer name in the schema directly fits the visible checkpoint; "
        "otherwise leave cv_config empty. Set coverage_review.complete=false and list omissions when the view cannot "
        "support a complete draft. "
        "Use only method_hint values listed in the schema. This is only a candidate draft and must never be described "
        "as confirmed. Return one complete, valid JSON object only, with no markdown or trailing text: "
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        + "\nCurrent SKU: "
        + json.dumps(current_sku, ensure_ascii=False, separators=(",", ":"))
    )
    reasons: list[str] = []
    selected = primary
    fallback_used = False
    try:
        value, elapsed = _vision_json(
            primary, data_url=data_url, prompt=prompt, max_tokens=1100,
        )
    except StudioAIError:
        if not (_env_enabled("STUDIO_VISION_FALLBACK_ENABLED", True) and fallback.configured):
            raise
        reasons.append("primary_error")
        value, elapsed = _vision_json(
            fallback, data_url=data_url, prompt=prompt, max_tokens=1100,
        )
        selected = fallback
        fallback_used = True
    result = _normalize_result(value, selected, elapsed, language)
    total_elapsed = elapsed
    passes = 1

    coverage = result.get("coverage_review")
    coverage_fallback = (
        _env_enabled("STUDIO_VISION_AUTHOR_COVERAGE_FALLBACK", True)
        and fallback.configured
        and selected.model != fallback.model
        and (not coverage or not coverage.get("complete"))
    )
    explicit_self_review = _env_enabled("STUDIO_VISION_AUTHOR_SELF_REVIEW", False)
    if coverage_fallback or explicit_self_review:
        review_prompt = (
            prompt
            + "\nA first-pass candidate follows. Perform an independent second coverage pass. "
            "Return a complete revised object, preserving valid points and adding every visible omitted point. "
            "Do not invent thresholds or hidden facts. First-pass candidate: "
            + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        )
        review_config = fallback if coverage_fallback else primary
        review_selected = review_config
        if coverage_fallback:
            reasons.append("primary_coverage_incomplete")
        try:
            reviewed_value, review_elapsed = _vision_json(
                review_config, data_url=data_url, prompt=review_prompt, max_tokens=1792,
            )
        except StudioAIError:
            if review_config.model == fallback.model or not (
                _env_enabled("STUDIO_VISION_FALLBACK_ENABLED", True) and fallback.configured
            ):
                reviewed_value = None
                review_elapsed = 0
                reasons.append("coverage_review_error")
            else:
                reasons.append("primary_self_review_error")
                reviewed_value, review_elapsed = _vision_json(
                    fallback, data_url=data_url, prompt=review_prompt, max_tokens=1792,
                )
                review_selected = fallback
                fallback_used = True
        if reviewed_value is not None:
            selected = review_selected
            if review_selected.model == fallback.model:
                fallback_used = True
            reviewed = _normalize_result(reviewed_value, review_selected, review_elapsed, language)
            result = _merge_authoring_results(result, reviewed)
            total_elapsed += review_elapsed
            passes = 2

    result["assistant"] = _assistant_route(
        selected=selected,
        elapsed_ms=total_elapsed,
        primary=primary,
        fallback=fallback,
        fallback_used=fallback_used,
        reasons=reasons,
        passes=passes,
    )
    return result


def _normalize_inspection(
    value: dict[str, Any],
    *,
    config: AssistantConfig,
    elapsed: int,
    checkpoint_contract: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_codes = [item["point_code"] for item in checkpoint_contract]
    returned: dict[str, dict[str, Any]] = {}
    for item in value.get("checkpoint_results") or []:
        if not isinstance(item, dict):
            raise StudioAIError("vision_inspection_result_not_object")
        code = str(item.get("point_code") or "").strip()
        if code not in expected_codes or code in returned:
            raise StudioAIError("vision_inspection_checkpoint_mismatch")
        result = str(item.get("result") or "").strip()
        if result not in {"pass", "fail", "not_visible", "low_confidence"}:
            raise StudioAIError("vision_inspection_result_invalid")
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        returned[code] = {
            "point_code": code, "result": result, "confidence": confidence,
            "observed_value": str(item.get("observed_value") or "").strip()[:256] or None,
            "notes": str(item.get("notes") or "").strip()[:2000] or None,
        }
    results = [
        returned.get(code) or {
            "point_code": code, "result": "not_visible", "confidence": 0.0,
            "observed_value": None, "notes": None,
        }
        for code in expected_codes
    ]
    return {
        "summary": str(value.get("summary") or "").strip()[:4000],
        "checkpoint_results": results,
        "assistant": {
            "role": "vision", "provider": config.provider, "model": config.model,
            "elapsed_ms": elapsed, "mode": "live",
        },
    }


def _inspection_escalation_reasons(result: dict[str, Any]) -> list[str]:
    threshold = _escalation_confidence()
    reasons: list[str] = []
    for item in result["checkpoint_results"]:
        code = item["point_code"]
        if item["result"] in {"not_visible", "low_confidence"}:
            reasons.append(f"{code}:{item['result']}")
        elif item["confidence"] < threshold:
            reasons.append(f"{code}:confidence_below_{threshold:g}")
    return reasons


def inspect_image(
    *,
    image_path: Path,
    mime_type: str,
    language: str,
    checkpoints: list[dict[str, Any]],
    cv_context: dict[str, Any] | None = None,
    fallback_crops: dict[str, list[Path]] | None = None,
) -> dict[str, Any]:
    """Run provider-neutral visual inspection against an exact checkpoint set.

    The model may propose checkpoint-level observations only. It cannot
    finalize a job, and a missing checkpoint is normalized to not_visible
    so incomplete model output can never silently pass.
    """
    if not checkpoints:
        raise StudioAIError("vision_inspection_has_no_checkpoints")
    primary = vision_config()
    fallback = vision_fallback_config()
    mime = mime_type or mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
    checkpoint_contract = [
        {
            "point_code": str(item.get("point_code") or ""),
            "label": str(item.get("label") or ""),
            "description": item.get("description"),
            "method_hint": item.get("method_hint"),
            "expected_value": item.get("expected_value"),
            "pass_criteria": item.get("pass_criteria"),
        }
        for item in checkpoints
    ]
    schema = {
        "summary": f"short evidence summary in {_locale_name(language)}",
        "checkpoint_results": [{
            "point_code": "one exact code from the supplied list",
            "result": "pass|fail|not_visible|low_confidence",
            "confidence": "number from 0 to 1",
            "observed_value": "visible observation or null",
            "notes": "brief evidence explanation",
        }],
    }
    def make_prompt(
        contract: list[dict[str, Any]],
        context: dict[str, Any] | None,
        crop_manifest: list[dict[str, Any]] | None = None,
    ) -> str:
        value = (
            "You are the vision inspection assistant for Giraffe QC. Inspect only the supplied image evidence "
            "against every supplied checkpoint. Return exactly one result for every point_code and do "
            "not add new point codes. Never guess hidden properties, dimensions, tolerances, barcode "
            "content, or evidence outside the image. If a checkpoint is not clearly visible, use "
            "not_visible; if evidence is ambiguous, use low_confidence. This is a checkpoint suggestion "
            "for operator review, not a final verdict. Return one valid JSON object only, no markdown: "
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            + "\nCheckpoints: "
            + json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
        )
        if crop_manifest:
            value += (
                "\nOnly per-checkpoint crops are supplied. Image numbers are 1-based and map as follows: "
                + json.dumps(crop_manifest, ensure_ascii=False, separators=(",", ":"))
            )
        if context:
            value += "\n" + build_prompt_block(context)
        return value

    prompt = make_prompt(checkpoint_contract, cv_context)

    def prepare_fallback(codes: list[str]):
        wanted = set(codes)
        contract = [c for c in checkpoint_contract if c["point_code"] in wanted]
        if not contract:
            return None
        if fallback_crops is None:
            return [data_url], contract, make_prompt(contract, cv_context), None
        urls: list[str] = []
        manifest: list[dict[str, Any]] = []
        available_codes: set[str] = set()
        for item in contract:
            code = item["point_code"]
            paths = fallback_crops.get(code) or []
            for path in paths:
                crop_path = Path(path)
                if not crop_path.is_file():
                    continue
                crop_mime = mimetypes.guess_type(crop_path.name)[0] or "image/jpeg"
                urls.append(
                    f"data:{crop_mime};base64,"
                    + base64.b64encode(crop_path.read_bytes()).decode("ascii")
                )
                available_codes.add(code)
                manifest.append({"image_index": len(urls), "point_code": code})
        if not urls:
            return None
        contract = [c for c in contract if c["point_code"] in available_codes]
        context = None
        if cv_context:
            context_points = [
                point for point in (cv_context.get("points") or [])
                if point.get("point_code") in available_codes
            ]
            if context_points:
                context = {
                    "schema_version": cv_context.get("schema_version", "1.0"),
                    "points": context_points,
                    "verdict_effect": "informational_only",
                }
        return urls, contract, make_prompt(contract, context, manifest), manifest

    reasons: list[str] = []
    fallback_used = False
    selected = primary
    try:
        value, primary_elapsed = _vision_json(
            primary, data_url=data_url, prompt=prompt, max_tokens=1024,
        )
        primary_result = _normalize_inspection(
            value, config=primary, elapsed=primary_elapsed,
            checkpoint_contract=checkpoint_contract,
        )
    except StudioAIError as primary_error:
        if not (_env_enabled("STUDIO_VISION_FALLBACK_ENABLED", True) and fallback.configured):
            raise
        reasons.append("primary_error")
        prepared = prepare_fallback([item["point_code"] for item in checkpoint_contract])
        if prepared is None:
            raise primary_error
        fallback_urls, fallback_contract, fallback_prompt, manifest = prepared
        fallback_value, fallback_elapsed = _vision_json(
            fallback, data_url=fallback_urls, prompt=fallback_prompt, max_tokens=1024,
        )
        result = _normalize_inspection(
            fallback_value, config=fallback, elapsed=fallback_elapsed,
            checkpoint_contract=checkpoint_contract,
        )
        result["assistant"] = _assistant_route(
            selected=fallback, elapsed_ms=fallback_elapsed, primary=primary,
            fallback=fallback, fallback_used=True, reasons=reasons,
        )
        result["routing"] = {
            "primary": None,
            "fallback": _normalize_inspection(
                fallback_value, config=fallback, elapsed=fallback_elapsed,
                checkpoint_contract=fallback_contract,
            )["checkpoint_results"],
            "fallback_payload": "full_image" if fallback_crops is None else "checkpoint_crops",
            "crop_manifest": manifest,
        }
        return result

    reasons.extend(_inspection_escalation_reasons(primary_result))
    result = primary_result
    total_elapsed = primary_elapsed
    routing: dict[str, Any] = {
        "primary": primary_result["checkpoint_results"], "fallback": None,
        "fallback_payload": None, "crop_manifest": None,
    }
    if reasons and _env_enabled("STUDIO_VISION_FALLBACK_ENABLED", True) and fallback.configured:
        escalated_codes = list(dict.fromkeys(reason.split(":", 1)[0] for reason in reasons))
        prepared = prepare_fallback(escalated_codes)
        if fallback_crops is not None:
            available = {
                item["point_code"] for item in (prepared[1] if prepared else [])
            }
            for code in escalated_codes:
                if code not in available:
                    reasons.append(f"{code}:no_fallback_crop")
        try:
            if prepared is None:
                raise StudioAIError("no_authorized_fallback_crop")
            fallback_urls, fallback_contract, fallback_prompt, manifest = prepared
            fallback_value, fallback_elapsed = _vision_json(
                fallback, data_url=fallback_urls, prompt=fallback_prompt, max_tokens=1024,
            )
            fallback_result = _normalize_inspection(
                fallback_value, config=fallback, elapsed=fallback_elapsed,
                checkpoint_contract=fallback_contract,
            )
        except StudioAIError as exc:
            reasons.append(f"fallback_error:{exc}")
        else:
            fallback_by_code = {
                item["point_code"]: item for item in fallback_result["checkpoint_results"]
            }
            result = dict(primary_result)
            result["summary"] = fallback_result["summary"] or primary_result["summary"]
            result["checkpoint_results"] = [
                fallback_by_code.get(item["point_code"], item)
                for item in primary_result["checkpoint_results"]
            ]
            total_elapsed += fallback_elapsed
            selected = fallback
            fallback_used = True
            routing["fallback"] = fallback_result["checkpoint_results"]
            routing["fallback_payload"] = (
                "full_image" if fallback_crops is None else "checkpoint_crops"
            )
            routing["crop_manifest"] = manifest
    result["assistant"] = _assistant_route(
        selected=selected, elapsed_ms=total_elapsed, primary=primary,
        fallback=fallback, fallback_used=fallback_used, reasons=reasons,
    )
    result["routing"] = routing
    return result


def assistant_status() -> dict[str, Any]:
    """Return configuration state without exposing internal endpoints."""
    def view(config: AssistantConfig) -> dict[str, Any]:
        return {
            "role": config.role,
            "configured": config.configured,
            "provider": config.provider if config.configured else None,
            "model": config.model if config.configured else None,
        }
    return {
        "text": view(text_config()),
        "vision": view(vision_config()),
        "vision_fallback": view(vision_fallback_config()),
        "vision_routing": {
            "strategy": "cv_then_primary_then_conditional_fallback",
            "escalation_confidence": _escalation_confidence(),
        },
    }
