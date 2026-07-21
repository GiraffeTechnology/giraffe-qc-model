from __future__ import annotations

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
    assert captured["payload"]["max_tokens"] == 768
    content = captured["payload"]["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "at most 3 high-value" in content[1]["text"]
    assert result["assistant"]["role"] == "vision"


def test_live_vision_inspection_is_checkpoint_scoped_and_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_PROVIDER", "openai_compatible")
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://vision.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "replaceable-vision-default")
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

    serialized = json.dumps(ai_gateway.assistant_status())
    assert "internal-text" not in serialized
    assert "internal-vision" not in serialized
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
