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

def text_output_tokens() -> int:
    """Bounded text-assistant output budget; four-point drafts exceed 512."""
    try:
        configured = int(os.getenv("STUDIO_TEXT_NUM_PREDICT", "1024"))
    except ValueError:
        configured = 1024
    return max(768, min(configured, 4096))



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
            "name": "rhinestone_count|pearl_count|petal_segmentation|pistil_localization",
            "params": {},
        }],
    },
}

_ALLOWED_CV_ANALYZERS = frozenset({
    "rhinestone_count", "pearl_count", "petal_segmentation", "pistil_localization",
})

_COUNT_CONCEPTS = {
    "petal": {
        "terms": ("花瓣", "petal", "petals"),
        "analyzer": "petal_segmentation",
        "params": {"backend": "silhouette"},
    },
    "pearl": {
        "terms": ("珍珠", "pearl", "pearls"),
        "analyzer": "pearl_count",
        "params": {},
    },
    "rhinestone": {
        "terms": ("水钻", "rhinestone", "rhinestones"),
        "analyzer": "rhinestone_count",
        "params": {"backend": "socket_holes"},
    },
}
_CENTER_TERMS = ("花蕊", "stamen", "pistil", "stigma")


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
    evidence = " ".join(filter(None, (
        point_code, label, checkpoint["description"], checkpoint["pass_criteria"],
    )))
    count_identity = bool(re.search(r"(?:COUNT|数量|数目|计数)", evidence, re.IGNORECASE))
    if count_identity:
        exact_count = re.search(
            r"(?:恰好|正好|仅[^0-9]{0,16}|必须(?:为|是|等于)?|应(?:为|是|等于)?|"
            r"exactly|must\s+(?:be|equal)?|shall\s+(?:be|equal)?)\s*(\d+)",
            evidence,
            flags=re.IGNORECASE,
        )
        if exact_count:
            checkpoint["method_hint"] = "counting"
            if not checkpoint["expected_value"]:
                checkpoint["expected_value"] = str(int(exact_count.group(1)))
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


def _mentions(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _explicit_count(text: str, terms: tuple[str, ...]) -> int | None:
    """Recover only a count explicitly written by the administrator."""
    alternatives = "|".join(sorted((re.escape(term) for term in terms), key=len, reverse=True))
    patterns = (
        rf"(?:{alternatives})(?:\s*(?:数量|数目|个数|count))?[^0-9]{{0,16}}(\d+)",
        rf"(\d+)\s*(?:个|颗|枚|pcs?)?\s*(?:{alternatives})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _explicit_center_bound(text: str | None) -> str | None:
    """Recover a centering bound only when the administrator supplied it."""
    if not text or not _mentions(text, _CENTER_TERMS):
        return None
    sentences = re.split(r"[。！？!?;；\n]+", text)
    for sentence in sentences:
        if not _mentions(sentence, _CENTER_TERMS):
            continue
        if not re.search(
            r"居中|中心|偏离|center(?:ed|ing)?|centre(?:d|ing)?|offset",
            sentence,
            re.IGNORECASE,
        ):
            continue
        bound = re.search(
            r"(?:≤|<=|不超过|不得超过|最多|最大(?:允许)?(?:偏移|误差)?(?:为)?|"
            r"maximum(?:\s+allowed)?(?:\s+(?:offset|deviation))?(?:\s+of)?|"
            r"within|±)\s*(\d+(?:\.\d+)?)\s*"
            r"(毫米|厘米|微米|mm|cm|μm|um|度|°|%)",
            sentence,
            flags=re.IGNORECASE,
        )
        if bound:
            units = {"毫米": "mm", "厘米": "cm", "微米": "μm"}
            unit = units.get(bound.group(2).lower(), bound.group(2))
            return f"≤{bound.group(1)} {unit}"
    return None


def _enforce_authoritative_text(
    checkpoints: list[dict[str, Any]], source_text: str | None,
) -> list[dict[str, Any]]:
    """Make explicit administrator facts authoritative over model typing.

    The text model is still called and authors the draft. This post-validation
    layer only preserves facts that are literally present in the administrator
    input, assigns the matching allow-listed CV hook, and removes complementary
    duplicates (for example, an exact pearl-count checkpoint plus a second
    "missing pearl" checkpoint). It never invents an absent count or tolerance.
    """
    if not source_text:
        return checkpoints
    explicit_counts = {
        concept: count
        for concept, spec in _COUNT_CONCEPTS.items()
        if (count := _explicit_count(source_text, spec["terms"])) is not None
    }
    center_requested = _mentions(source_text, _CENTER_TERMS) and bool(
        re.search(
            r"居中|中心|偏离|center(?:ed|ing)?|centre(?:d|ing)?|offset",
            source_text,
            re.IGNORECASE,
        )
    )
    center_bound = _explicit_center_bound(source_text)
    seen_counts: set[str] = set()
    seen_center = False
    result: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        identity = " ".join(filter(None, (
            checkpoint.get("point_code"), checkpoint.get("label"),
            checkpoint.get("description"), checkpoint.get("pass_criteria"),
        )))
        concept = next((
            name for name, spec in _COUNT_CONCEPTS.items()
            if name in explicit_counts and _mentions(identity, spec["terms"])
        ), None)
        if concept:
            if concept in seen_counts:
                continue
            spec = _COUNT_CONCEPTS[concept]
            expected = explicit_counts[concept]
            checkpoint["method_hint"] = "counting"
            checkpoint["expected_value"] = str(expected)
            checkpoint["expected_features"] = {spec["analyzer"]: expected}
            checkpoint["cv_config"] = {
                "analyzers": [{"name": spec["analyzer"], "params": dict(spec["params"])}]
            }
            seen_counts.add(concept)
        elif center_requested and _mentions(identity, _CENTER_TERMS):
            if seen_center:
                continue
            checkpoint["method_hint"] = "alignment"
            checkpoint["cv_config"] = {
                "analyzers": [{"name": "pistil_localization", "params": {}}]
            }
            # The model is not an authority for tolerances. Remove every
            # free-text/numeric constraint it authored and restore only an
            # exact bound that is literally present in the administrator's
            # source text.
            checkpoint["expected_value"] = center_bound
            checkpoint["description"] = None
            checkpoint["pass_criteria"] = None
            checkpoint["expected_features"] = {}
            seen_center = True
        result.append(checkpoint)
    return result


def _normalize_result(
    value: dict[str, Any],
    config: AssistantConfig,
    elapsed_ms: int,
    language: str,
    source_text: str | None = None,
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
    checkpoints = _enforce_authoritative_text(checkpoints, source_text)
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
    center_requested = bool(source_text) and _mentions(source_text or "", _CENTER_TERMS) and bool(
        re.search(
            r"居中|中心|偏离|center(?:ed|ing)?|centre(?:d|ing)?|offset",
            source_text or "",
            re.IGNORECASE,
        )
    )
    if center_requested and _explicit_center_bound(source_text) is None:
        alignment_points = [
            cp for cp in checkpoints
            if cp["method_hint"] == "alignment" and _mentions(
                " ".join(filter(None, (
                    cp.get("point_code"), cp.get("label"),
                ))),
                _CENTER_TERMS,
            )
        ]
        if alignment_points:
            # Replace any model-authored tolerance question with one
            # deterministic, localized unresolved field. A confirmation must
            # remain blocked until the administrator provides the boundary.
            questions = [
                q for q in questions
                if not (
                    _mentions(f"{q['field']} {q['question']}", _CENTER_TERMS)
                    or re.search(
                        r"center|centre|offset|alignment|threshold_for_centering",
                        f"{q['field']} {q['question']}",
                        re.IGNORECASE,
                    )
                )
            ]
            checkpoint = alignment_points[0]
            question = {
                "zh-CN": "请提供花蕊居中的最大允许偏移量（含单位）。",
                "ja": "花芯の中心ずれの最大許容値（単位を含む）を指定してください。",
            }.get(language, "Provide the maximum allowed stamen offset, including its unit.")
            questions.append({
                "field": f"{checkpoint['point_code']}.alignment_tolerance",
                "question": question,
            })
    resolved = [cp for cp in checkpoints if cp["expected_value"]]
    if resolved:
        questions = [q for q in questions if not any(
            q["field"].upper().startswith(cp["point_code"])
            or cp["point_code"] in q["question"].upper()
            or cp["label"].lower() in q["question"].lower()
            for cp in resolved
        )]
    if source_text:
        configured_terms = tuple(
            term
            for spec in _COUNT_CONCEPTS.values()
            if _explicit_count(source_text, spec["terms"]) is not None
            for term in spec["terms"]
        )
        questions = [q for q in questions if not (
            configured_terms
            and _mentions(q["question"], configured_terms)
            and re.search(
                r"analyzers?\[?\d*\]?\.name|analyzer\s+name|分析器名称",
                f"{q['field']} {q['question']}",
                re.IGNORECASE,
            )
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
        "Use method_hint=counting and copy the exact number into expected_value for every explicit count. "
        "Use method_hint=alignment for centered or offset criteria. One criterion must produce exactly one checkpoint: "
        "do not add a separate missing/absence checkpoint when an exact-count checkpoint already covers it, and do not "
        "duplicate a centered criterion as a second offset checkpoint. "
        "Keep labels, descriptions, criteria, and replies concise. Omit empty optional fields. "
        "Return exactly one complete JSON object, with no markdown. Never stop before closing the JSON object. "
        "Required schema: "
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
            "options": {"temperature": 0, "num_predict": text_output_tokens()},
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
    return _normalize_result(
        _clean_json(str(raw)), config, elapsed, language, source_text=message,
    )


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
    value, elapsed = _vision_json(
        primary, data_url=data_url, prompt=prompt, max_tokens=2048,
    )
    text = str(value.get("text") or "").strip()
    if not text:
        raise StudioAIError("vision_ocr_no_readable_text")
    return {
        "text": text[:2_000_000],
        "language": str(value.get("language") or "").strip()[:64] or None,
        "layout_notes": str(value.get("layout_notes") or "").strip()[:2000] or None,
        "assistant": {
            "role": "vision", "provider": primary.provider, "model": primary.model,
            "elapsed_ms": elapsed, "mode": "live",
        },
    }


def author_image(*, image_path: Path, mime_type: str, language: str, current_sku: dict[str, Any]) -> dict[str, Any]:
    """Describe a reference photo for the administrator.

    Correction (2026-07-22): detection points are authored by the
    administrator — through the Studio conversation or an uploaded process
    card — never generated by the vision assistant from a photo. This call
    only summarizes what the photo shows and asks for the facts the
    administrator must supply; any checkpoint list the model volunteers is
    discarded before it can reach the confirmation flow.
    """
    primary = vision_config()
    mime = mime_type or mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
    schema = {
        "intent": "provide_details",
        "reply": f"one-sentence visible summary in {_locale_name(language)}",
        "sku": {},
        "questions": [{"field": "standard", "question": "fact the administrator must provide"}],
    }
    prompt = (
        "You are the vision assistant for Giraffe QC standard authoring. Describe this reference photo only. "
        "Summarize the visible attributes (components, arrangement, surface, color/finish, markings) in one sentence. "
        "Detection points are defined by the administrator through the conversation or an uploaded process card — "
        "do NOT propose, draft, or list inspection checkpoints. Do not infer hidden material properties, exact "
        "dimensions, tolerances, counts obscured by the view, or business rules. Ask concise questions for the facts "
        "the administrator must provide, each under 20 words. "
        "Return one complete, valid JSON object only, with no markdown or trailing text: "
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        + "\nCurrent SKU: "
        + json.dumps(current_sku, ensure_ascii=False, separators=(",", ":"))
    )
    value, elapsed = _vision_json(
        primary, data_url=data_url, prompt=prompt, max_tokens=700,
    )
    result = _normalize_result(value, primary, elapsed, language)
    # The administrator is the only checkpoint source: discard anything the
    # model volunteered so photo analysis can never seed the confirmation flow.
    result["checkpoints"] = []
    result.pop("coverage_review", None)
    return result


_INT_RE = re.compile(r"-?\d+")


def _extract_int(text: str | None) -> int | None:
    """Pull the first integer out of a free-text observation, or None."""
    if not text:
        return None
    match = _INT_RE.search(text)
    return int(match.group()) if match else None


def _cv_counts_by_point(cv_context: dict[str, Any] | None) -> dict[str, int]:
    """Map point_code -> CV analyzer count, for points where CV reported one."""
    counts: dict[str, int] = {}
    if not cv_context:
        return counts
    for point in cv_context.get("points") or []:
        code = point.get("point_code")
        analysis = point.get("analysis") or {}
        for entry in analysis.get("analyzers") or []:
            count = entry.get("count")
            if code and isinstance(count, int):
                counts[code] = count
                break
    return counts


def _normalize_inspection(
    value: dict[str, Any],
    *,
    config: AssistantConfig,
    elapsed: int,
    checkpoint_contract: list[dict[str, Any]],
    cv_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and normalize one model response.

    Audit 2026-07-22 (§8.1): a live model response marked a checkpoint's CV
    count as "supported" while its own ``observed_value`` for that same
    point stated a different number — an internally self-contradictory
    response that the prior schema had no way to catch, since "supported"
    was only ever expressed as free text. ``cv_agreement`` makes that claim
    structured and machine-checkable: when the model asserts ``"agrees"``
    for a point whose CV evidence reports a numeric count, and its own
    parsed ``observed_value`` states a different number, the response is
    rejected here — fail closed via the same StudioAIError path that already
    triggers primary/fallback escalation, rather than trusting a
    self-contradictory claim.

    STAGE2_QWEN_VISION_PRODUCTION_ASSESSMENT (2026-07-22): a blind 30B/4B
    count on the raw photo got 2 of 3 items wrong with high stated
    confidence — the vision model is not a reliable counter. CV must be the
    counting authority; the vision model's role on a counting checkpoint is
    limited to confirming or disputing the CV count, never substituting its
    own freely generated number as the production observation. So for any
    ``method_hint == "counting"`` checkpoint: if CV reports a count, that
    count — not the model's text — becomes the recorded ``observed_value``,
    and an honest ``"disagrees"`` downgrades the result to
    ``low_confidence`` for human review rather than being accepted as a
    confident pass. If CV has no detector configured for that point at all,
    the checkpoint can never be autonomously passed on the model's own
    guess — it is forced to ``low_confidence`` so it always reaches a human,
    matching "CV 未可靠定位时必须停止" from the assessment's root-cause
    analysis.
    """
    expected_codes = [item["point_code"] for item in checkpoint_contract]
    method_hints = {item["point_code"]: item.get("method_hint") for item in checkpoint_contract}
    cv_counts = _cv_counts_by_point(cv_context)
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
        observed_value = str(item.get("observed_value") or "").strip()[:256] or None
        cv_agreement = str(item.get("cv_agreement") or "").strip().lower() or None
        if cv_agreement == "agrees" and code in cv_counts:
            observed_int = _extract_int(observed_value)
            if observed_int is not None and observed_int != cv_counts[code]:
                raise StudioAIError(
                    f"vision_inspection_cv_agreement_contradicts_observed_value:{code}"
                )
        notes = str(item.get("notes") or "").strip()[:2000] or None
        if method_hints.get(code) == "counting":
            if code in cv_counts:
                observed_value = str(cv_counts[code])
                if cv_agreement == "disagrees" and result == "pass":
                    result = "low_confidence"
                    notes = " ".join(filter(None, [notes, "model_disputes_cv_count_review_required"]))
            else:
                result = "low_confidence"
                notes = " ".join(filter(None, [notes, "no_cv_detector_configured_for_counting_checkpoint"]))
        returned[code] = {
            "point_code": code, "result": result, "confidence": confidence,
            "observed_value": observed_value,
            "notes": notes,
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


_PRODUCTION_VLM_METHOD_HINTS = frozenset({"counting", "defect_detection"})


def _excluded_checkpoint_result(code: str, method_hint: str | None) -> dict[str, Any]:
    return {
        "point_code": code, "result": "low_confidence", "confidence": 0.0,
        "observed_value": None,
        "notes": f"vlm_scope_excludes_method_hint:{method_hint or 'unset'}",
    }


def inspect_image(
    *,
    image_path: Path,
    mime_type: str,
    language: str,
    checkpoints: list[dict[str, Any]],
    cv_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run provider-neutral visual inspection against an exact checkpoint set.

    The model may propose checkpoint-level observations only. It cannot
    finalize a job, and a missing checkpoint is normalized to not_visible
    so incomplete model output can never silently pass.

    STAGE2_QWEN_VISION_PRODUCTION_ASSESSMENT (2026-07-22): production scopes
    the vision model to two jobs only — counting confirmation
    (``method_hint == "counting"``, see ``_normalize_inspection``'s CV
    counting-authority rule) and obvious-defect detection
    (``method_hint == "defect_detection"``, e.g. a missing/dropped stone).
    A checkpoint typed with any other method_hint (alignment,
    presence_check, shape_compare, readability_check) is never sent to the
    model in production; it is returned as low_confidence so it always
    reaches a human instead of asking the model to judge something outside
    its validated scope. There is no escalation to a larger/remote model on
    a low-confidence or ambiguous result — the on-device model is the only
    vision model in this path, and operator review is the fallback.
    """
    if not checkpoints:
        raise StudioAIError("vision_inspection_has_no_checkpoints")
    primary = vision_config()
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
    vlm_contract = [c for c in checkpoint_contract if c["method_hint"] in _PRODUCTION_VLM_METHOD_HINTS]
    excluded_results = {
        c["point_code"]: _excluded_checkpoint_result(c["point_code"], c["method_hint"])
        for c in checkpoint_contract if c["method_hint"] not in _PRODUCTION_VLM_METHOD_HINTS
    }
    if not vlm_contract:
        return {
            "summary": "No checkpoints are within the production vision model's scope "
                       "(counting or defect_detection); all require human inspection.",
            "checkpoint_results": [excluded_results[c["point_code"]] for c in checkpoint_contract],
            "assistant": {
                "role": "vision", "provider": None, "model": None,
                "elapsed_ms": 0, "mode": "not_called",
            },
        }
    schema = {
        "summary": f"short evidence summary in {_locale_name(language)}",
        "checkpoint_results": [{
            "point_code": "one exact code from the supplied list",
            "result": "pass|fail|not_visible|low_confidence",
            "confidence": "number from 0 to 1",
            "observed_value": "visible observation or null",
            "notes": "brief evidence explanation",
            "cv_agreement": "agrees|disagrees|not_applicable — only when CV pre-analysis evidence is supplied for this point; state 'agrees' only if your own observed_value matches the CV count exactly, otherwise 'disagrees'",
        }],
    }
    counting_rule = (
        "You handle exactly two kinds of checkpoints: counting confirmation and obvious-defect "
        "detection (e.g. a missing/dropped stone, visible damage, misalignment). For a checkpoint "
        "whose method_hint is 'counting': CV is the counting authority, not you. If CV pre-analysis "
        "evidence is supplied for that point, do not invent your own count — compare what you see to "
        "the CV count and report cv_agreement ('agrees' or 'disagrees') plus any visible defect in "
        "notes; the recorded count always comes from CV, never from your own tally. If no CV evidence "
        "is supplied for a counting checkpoint, you cannot supply a trustworthy count yourself — use "
        "low_confidence rather than guessing a number."
    )

    def make_prompt(contract: list[dict[str, Any]], context: dict[str, Any] | None) -> str:
        value = (
            "You are the vision inspection assistant for Giraffe QC. Inspect only the supplied image evidence "
            "against every supplied checkpoint. Return exactly one result for every point_code and do "
            "not add new point codes. Never guess hidden properties, dimensions, tolerances, barcode "
            "content, or evidence outside the image. If a checkpoint is not clearly visible, use "
            "not_visible; if evidence is ambiguous, use low_confidence. This is a checkpoint suggestion "
            "for operator review, not a final verdict. " + counting_rule + " "
            "Return one valid JSON object only, no markdown: "
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            + "\nCheckpoints: "
            + json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
        )
        if context:
            value += "\n" + build_prompt_block(context)
        return value

    prompt = make_prompt(vlm_contract, cv_context)
    value, elapsed = _vision_json(
        primary, data_url=data_url, prompt=prompt, max_tokens=1024,
    )
    result = _normalize_inspection(
        value, config=primary, elapsed=elapsed,
        checkpoint_contract=vlm_contract, cv_context=cv_context,
    )
    by_code = {item["point_code"]: item for item in result["checkpoint_results"]}
    result["checkpoint_results"] = [
        by_code.get(c["point_code"]) or excluded_results.get(c["point_code"])
        for c in checkpoint_contract
    ]
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
    }
