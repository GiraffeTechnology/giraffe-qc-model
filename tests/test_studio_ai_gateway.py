from __future__ import annotations

import base64
import json

from src.qc_model.studio import ai_gateway


def test_text_assistant_uses_configured_ollama_route_and_strict_draft(monkeypatch):
    monkeypatch.setenv("STUDIO_TEXT_PROVIDER", "ollama_compatible")
    monkeypatch.setenv("STUDIO_TEXT_BASE_URL", "http://assistant.invalid")
    monkeypatch.setenv("STUDIO_TEXT_MODEL", "replaceable-text-default")
    captured = {}

    def fake_post(config, payload, path):
        captured.update(config=config, payload=payload, path=path)
        content = {
            "intent": "define_requirements",
            "reply": "我已生成候选检测点，请审核。",
            "sku": {},
            "checkpoints": [{
                "point_code": "pearl count",
                "label": "珍珠数量",
                "method_hint": "counting",
                "severity": "critical",
                "expected_value": None,
                "pass_criteria": "数量必须符合确认值",
            }],
            "questions": [],
        }
        return {"message": {"content": json.dumps(content, ensure_ascii=False)}}, 1250

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.author_text(
        message="这个胸针要检查珍珠数量",
        language="zh-CN",
        current_sku={"item_number": "FLW-001"},
    )

    assert captured["path"] == "/api/chat"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["think"] is False
    assert result["assistant"] == {
        "role": "text",
        "provider": "ollama_compatible",
        "model": "replaceable-text-default",
        "elapsed_ms": 1250,
        "mode": "live",
    }
    assert result["checkpoints"][0]["point_code"] == "PEARL_COUNT"
    assert result["questions"][0]["field"] == "PEARL_COUNT.expected_value"


def test_vision_assistant_sends_image_to_openai_compatible_route(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_PROVIDER", "openai_compatible")
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://vision.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "replaceable-vision-default")
    monkeypatch.setenv("STUDIO_VISION_AUTHOR_SELF_REVIEW", "false")
    image = tmp_path / "reference.png"
    image.write_bytes(b"not-decoded-by-the-gateway")
    captured = {}

    def fake_post(config, payload, path):
        captured.update(payload=payload, path=path)
        content = {
            "intent": "define_requirements",
            "reply": "One visible surface checkpoint is proposed.",
            "sku": {},
            "checkpoints": [{
                "point_code": "SURFACE_DAMAGE",
                "label": "Surface damage",
                "description": "Visible face must be intact",
                "method_hint": "defect_detection",
                "severity": "major",
                "expected_value": None,
                "pass_criteria": "No visible scratches or cracks",
            }],
            "questions": [],
        }
        return {"choices": [{"message": {"content": json.dumps(content)}}]}, 300

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.author_image(
        image_path=image,
        mime_type="image/png",
        language="en",
        current_sku={"item_number": "VIS-001"},
    )

    assert captured["path"] == "/v1/chat/completions"
    assert captured["payload"]["max_tokens"] == 700
    content = captured["payload"]["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "Describe this reference photo only" in content[1]["text"]
    assert "do NOT propose" in content[1]["text"]
    assert result["assistant"]["role"] == "vision"
    # Checkpoints are authored by the administrator, never from the photo.
    assert result["checkpoints"] == []


def test_live_vision_inspection_is_checkpoint_scoped_and_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_PROVIDER", "openai_compatible")
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://vision.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "replaceable-vision-default")
    monkeypatch.delenv("STUDIO_VISION_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("STUDIO_VISION_FALLBACK_MODEL", raising=False)
    image = tmp_path / "capture.png"
    image.write_bytes(b"camera-frame")
    captured = {}

    def fake_post(config, payload, path):
        captured.update(payload=payload, path=path)
        content = {
            "summary": "The barcode is visible but the seal is outside the frame.",
            "checkpoint_results": [{
                "point_code": "BARCODE_PRESENT",
                "result": "pass",
                "confidence": 0.91,
                "observed_value": "barcode label visible",
                "notes": "label is visible in the center",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(content)}}]}, 420

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image,
        mime_type="image/png",
        language="en",
        checkpoints=[
            {"point_code": "BARCODE_PRESENT", "label": "Barcode present"},
            {"point_code": "SEAL_INTEGRITY", "label": "Seal integrity"},
        ],
    )

    assert captured["path"] == "/v1/chat/completions"
    prompt = captured["payload"]["messages"][0]["content"][1]["text"]
    assert "every supplied checkpoint" in prompt
    assert "not a final verdict" in prompt
    assert result["checkpoint_results"][0]["result"] == "pass"
    assert result["checkpoint_results"][1] == {
        "point_code": "SEAL_INTEGRITY",
        "result": "not_visible",
        "confidence": 0.0,
        "observed_value": None,
        "notes": None,
    }
    assert result["assistant"]["model"] == "replaceable-vision-default"


def test_status_never_exposes_internal_endpoint(monkeypatch):
    monkeypatch.setenv("STUDIO_TEXT_BASE_URL", "http://internal-text:11434")
    monkeypatch.setenv("STUDIO_TEXT_MODEL", "text-default")
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://internal-vision:8080")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "vision-default")
    monkeypatch.setenv("STUDIO_VISION_FALLBACK_BASE_URL", "http://secret-fallback:18081")
    monkeypatch.setenv("STUDIO_VISION_FALLBACK_MODEL", "vision-fallback")

    serialized = json.dumps(ai_gateway.assistant_status())
    assert "internal-text" not in serialized
    assert "internal-vision" not in serialized
    assert "secret-fallback" not in serialized
    assert '"configured": true' in serialized


def test_explicit_bound_is_normalized_without_guessing():
    checkpoint = ai_gateway._validate_checkpoint({
        "point_code": "EDGE_TOLERANCE",
        "label": "边缘位置公差",
        "description": "允许偏移不超过2毫米",
        "method_hint": "alignment",
        "severity": "major",
        "expected_value": None,
        "pass_criteria": "偏差绝对值≤2mm",
    })
    assert checkpoint["expected_value"] == "≤2 mm"

    unknown = ai_gateway._validate_checkpoint({
        "point_code": "EDGE_TOLERANCE",
        "label": "Edge tolerance",
        "method_hint": "alignment",
        "pass_criteria": "Must be within the approved tolerance",
    })
    assert unknown["expected_value"] is None


def test_clean_json_accepts_complete_object_with_model_suffix():
    value = ai_gateway._clean_json(
        '```json\n{"intent":"help","reply":"ready"}\n```}'
    )
    assert value == {"intent": "help", "reply": "ready"}


def test_clean_json_still_rejects_truncated_object():
    try:
        ai_gateway._clean_json('{"intent":"help","reply":"ready"')
    except ai_gateway.StudioAIError as exc:
        assert str(exc) == "assistant_response_invalid_json"
    else:
        raise AssertionError("truncated assistant JSON must fail closed")


def test_author_image_discards_model_volunteered_checkpoints(monkeypatch, tmp_path):
    """Correction 2026-07-22: checkpoints are authored by the administrator
    (chat or process card). Photo analysis must never seed candidates, even
    when the model volunteers them."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    monkeypatch.delenv("STUDIO_VISION_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("STUDIO_VISION_FALLBACK_MODEL", raising=False)
    image = tmp_path / "reference.png"
    image.write_bytes(b"reference")
    prompts = []

    def fake_post(config, payload, path):
        prompts.append(payload["messages"][0]["content"][1]["text"])
        value = {
            "intent": "define_requirements", "reply": "Photo shows a flower.", "sku": {},
            "checkpoints": [{
                "point_code": "PETAL_SHAPE", "label": "Petal shape",
                "method_hint": "shape_compare", "severity": "major",
                "pass_criteria": "Visible petals are symmetric",
            }],
            "questions": [{"field": "standard", "question": "Which features must be checked?"}],
            "coverage_review": {"complete": True, "checked_dimensions": ["shape"], "omissions": []},
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.author_image(
        image_path=image, mime_type="image/png", language="en",
        current_sku={"item_number": "FLOWER-1"},
    )

    # Single descriptive pass; no candidate generation, no coverage machinery.
    assert len(prompts) == 1
    assert "do NOT propose" in prompts[0]
    assert result["checkpoints"] == []
    assert "coverage_review" not in result
    assert result["questions"]
    assert result["assistant"]["passes"] == 1


def test_inspection_injects_cv_and_escalates_low_confidence_to_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    monkeypatch.setenv("STUDIO_VISION_FALLBACK_BASE_URL", "http://fallback.invalid")
    monkeypatch.setenv("STUDIO_VISION_FALLBACK_MODEL", "cloud-30b")
    monkeypatch.setenv("STUDIO_VISION_ESCALATION_CONFIDENCE", "0.8")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")
    calls = []

    def fake_post(config, payload, path):
        prompt = payload["messages"][0]["content"][1]["text"]
        calls.append((config.model, prompt))
        low = config.model == "local-4b"
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "CENTER_ALIGNMENT",
                "result": "low_confidence" if low else "pass",
                "confidence": 0.55 if low else 0.94,
                "observed_value": "center visible",
                "notes": "evidence",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 120

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{"point_code": "CENTER_ALIGNMENT", "label": "Center alignment"}],
        cv_context={
            "schema_version": "1.0",
            "points": [{"point_code": "CENTER_ALIGNMENT", "analysis": {"analyzers": []}}],
        },
    )

    assert [model for model, _ in calls] == ["local-4b", "cloud-30b"]
    assert "<CV_PREANALYSIS_JSON>" in calls[0][1]
    assert result["checkpoint_results"][0]["result"] == "pass"
    assert result["assistant"]["fallback_used"] is True
    assert result["assistant"]["route"] == "fallback"
    assert "CENTER_ALIGNMENT:low_confidence" in result["assistant"]["escalation_reasons"]
    assert result["routing"]["primary"][0]["result"] == "low_confidence"


def test_inspection_fallback_receives_only_authorized_checkpoint_crop(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    monkeypatch.setenv("STUDIO_VISION_FALLBACK_BASE_URL", "http://fallback.invalid")
    monkeypatch.setenv("STUDIO_VISION_FALLBACK_MODEL", "cloud-30b")
    full_image = tmp_path / "full-frame.png"
    crop = tmp_path / "center-crop.jpg"
    full_image.write_bytes(b"full-frame-must-not-reach-fallback")
    crop.write_bytes(b"authorized-checkpoint-crop")
    calls = []

    def fake_post(config, payload, path):
        content = payload["messages"][0]["content"]
        calls.append((config.model, content))
        low = config.model == "local-4b"
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "CENTER_ALIGNMENT",
                "result": "low_confidence" if low else "pass",
                "confidence": 0.45 if low else 0.96,
                "observed_value": "center visible",
                "notes": "evidence",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=full_image, mime_type="image/png", language="en",
        checkpoints=[{"point_code": "CENTER_ALIGNMENT", "label": "Center alignment"}],
        fallback_crops={"CENTER_ALIGNMENT": [crop]},
    )

    assert [model for model, _ in calls] == ["local-4b", "cloud-30b"]
    fallback_images = [item["image_url"]["url"] for item in calls[1][1] if item["type"] == "image_url"]
    assert len(fallback_images) == 1
    assert base64.b64encode(crop.read_bytes()).decode("ascii") in fallback_images[0]
    assert base64.b64encode(full_image.read_bytes()).decode("ascii") not in fallback_images[0]
    assert result["routing"]["fallback_payload"] == "checkpoint_crops"
    assert result["routing"]["crop_manifest"] == [
        {"image_index": 1, "point_code": "CENTER_ALIGNMENT"},
    ]


def test_inspection_does_not_send_full_frame_when_checkpoint_has_no_crop(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    monkeypatch.setenv("STUDIO_VISION_FALLBACK_BASE_URL", "http://fallback.invalid")
    monkeypatch.setenv("STUDIO_VISION_FALLBACK_MODEL", "cloud-30b")
    image = tmp_path / "full-frame.png"
    image.write_bytes(b"full-frame")
    calls = []

    def fake_post(config, payload, path):
        calls.append(config.model)
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "CENTER_ALIGNMENT", "result": "not_visible",
                "confidence": 0.2, "observed_value": None, "notes": "unclear",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{"point_code": "CENTER_ALIGNMENT", "label": "Center alignment"}],
        fallback_crops={},
    )

    assert calls == ["local-4b"]
    assert result["assistant"]["fallback_used"] is False
    assert "CENTER_ALIGNMENT:no_fallback_crop" in result["assistant"]["escalation_reasons"]
    assert result["routing"]["fallback"] is None


def test_process_card_image_ocr_preserves_numbers_units_and_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    monkeypatch.delenv("STUDIO_VISION_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("STUDIO_VISION_FALLBACK_MODEL", raising=False)
    image = tmp_path / "card.png"
    image.write_bytes(b"card")
    captured = {}

    def fake_post(config, payload, path):
        captured.update(payload=payload, path=path)
        value = {
            "text": "Rivet diameter 5.0 mm ± 0.2 mm",
            "language": "en",
            "layout_notes": "one table row",
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 88

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.extract_image_text(
        image_path=image, mime_type="image/png", language="en",
    )

    assert result["text"] == "Rivet diameter 5.0 mm ± 0.2 mm"
    assert result["assistant"]["model"] == "local-4b"
    prompt = captured["payload"]["messages"][0]["content"][1]["text"]
    assert "Preserve numbers, units, tolerances" in prompt
