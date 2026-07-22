from __future__ import annotations

import json

import pytest

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
    assert captured["payload"]["options"]["num_predict"] == 1024
    assert result["checkpoints"][0]["point_code"] == "PEARL_COUNT"

    assert result["questions"][0]["field"] == "PEARL_COUNT.expected_value"
def test_text_output_budget_is_configurable_and_bounded(monkeypatch):
    monkeypatch.setenv("STUDIO_TEXT_NUM_PREDICT", "1536")
    assert ai_gateway.text_output_tokens() == 1536
    monkeypatch.setenv("STUDIO_TEXT_NUM_PREDICT", "100")
    assert ai_gateway.text_output_tokens() == 768
    monkeypatch.setenv("STUDIO_TEXT_NUM_PREDICT", "99999")
    assert ai_gateway.text_output_tokens() == 4096
    monkeypatch.setenv("STUDIO_TEXT_NUM_PREDICT", "invalid")
    assert ai_gateway.text_output_tokens() == 1024



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
    assert captured["payload"]["max_tokens"] == 700
    content = captured["payload"]["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "Describe this reference photo only" in content[1]["text"]
    assert "do NOT propose" in content[1]["text"]
    assert result["assistant"] == {
        "role": "vision",
        "provider": "openai_compatible",
        "model": "replaceable-vision-default",
        "elapsed_ms": 300,
        "mode": "live",
    }
    # Checkpoints are authored by the administrator, never from the photo.
    assert result["checkpoints"] == []


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
            "summary": "A defect is visible on one checkpoint; the other is outside the frame.",
            "checkpoint_results": [{
                "point_code": "SURFACE_DAMAGE",
                "result": "pass",
                "confidence": 0.91,
                "observed_value": "no visible damage",
                "notes": "surface is intact",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(content)}}]}, 420

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image,
        mime_type="image/png",
        language="en",
        checkpoints=[
            {"point_code": "SURFACE_DAMAGE", "label": "Surface damage", "method_hint": "defect_detection"},
            {"point_code": "SEAL_INTEGRITY", "label": "Seal integrity", "method_hint": "defect_detection"},
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


def test_inspection_excludes_checkpoints_outside_production_vlm_scope(monkeypatch, tmp_path):
    """STAGE2_QWEN_VISION_PRODUCTION_ASSESSMENT_20260722: production narrows
    the vision model to counting confirmation and obvious-defect detection
    only. A checkpoint typed with any other method_hint must never reach the
    model — it is returned as low_confidence so it always routes to a
    human, instead of asking the model to judge outside its validated
    scope."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")
    calls = []

    def fake_post(config, payload, path):
        calls.append(config.model)
        contract = json.loads(
            payload["messages"][0]["content"][1]["text"].split("Checkpoints: ", 1)[1].split("\n", 1)[0]
        )
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": item["point_code"], "result": "pass", "confidence": 0.9,
                "observed_value": "7", "notes": "matches CV",
            } for item in contract],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[
            {"point_code": "SURFACE_DAMAGE", "label": "Surface damage", "method_hint": "defect_detection"},
            {"point_code": "CENTER_ALIGNMENT", "label": "Center alignment", "method_hint": "alignment"},
            {"point_code": "LOGO_PRESENT", "label": "Logo present", "method_hint": "presence_check"},
        ],
    )

    assert calls == ["local-4b"]  # exactly one call, only for the in-scope checkpoint
    by_code = {item["point_code"]: item for item in result["checkpoint_results"]}
    assert by_code["SURFACE_DAMAGE"]["result"] == "pass"
    assert by_code["CENTER_ALIGNMENT"]["result"] == "low_confidence"
    assert by_code["CENTER_ALIGNMENT"]["notes"] == "vlm_scope_excludes_method_hint:alignment"
    assert by_code["LOGO_PRESENT"]["result"] == "low_confidence"
    assert by_code["LOGO_PRESENT"]["notes"] == "vlm_scope_excludes_method_hint:presence_check"


def test_inspection_skips_model_call_entirely_when_no_checkpoint_is_in_scope(monkeypatch, tmp_path):
    """No network call at all when every checkpoint is outside production
    scope — nothing to ask the model, so no reason to spend a call on it."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")
    calls = []

    def fake_post(config, payload, path):
        calls.append(config.model)
        raise AssertionError("must not call the model when nothing is in scope")

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{"point_code": "LABEL_READABLE", "label": "Label readable", "method_hint": "readability_check"}],
    )

    assert calls == []
    assert result["checkpoint_results"][0]["result"] == "low_confidence"
    assert result["checkpoint_results"][0]["notes"] == "vlm_scope_excludes_method_hint:readability_check"
    assert result["assistant"]["mode"] == "not_called"


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


def test_live_text_draft_preserves_explicit_counts_and_coalesces_complements(monkeypatch):
    """Explicit administrator facts remain authoritative over model typing."""
    monkeypatch.setenv("STUDIO_TEXT_PROVIDER", "ollama_compatible")
    monkeypatch.setenv("STUDIO_TEXT_BASE_URL", "http://assistant.invalid")
    monkeypatch.setenv("STUDIO_TEXT_MODEL", "replaceable-text-default")

    def fake_post(config, payload, path):
        content = {
            "intent": "define_requirements",
            "reply": "draft",
            "sku": {},
            "checkpoints": [
                {"point_code": "PETAL_COUNT_CHECK", "label": "花瓣数量检查", "method_hint": "defect_detection", "severity": "critical", "pass_criteria": "检测到且仅检测到4个花瓣"},
                {"point_code": "PEARL_COUNT_CHECK", "label": "珍珠数量检查", "method_hint": "defect_detection", "severity": "critical", "pass_criteria": "检测到且仅检测到3颗珍珠"},
                {"point_code": "PEARL_MISSING_CHECK", "label": "珍珠缺失检查", "method_hint": "defect_detection", "severity": "major", "pass_criteria": "不得缺失"},
                {"point_code": "RHINESTONE_COUNT_CHECK", "label": "水钻数量检查", "method_hint": "defect_detection", "severity": "critical", "pass_criteria": "检测到且仅检测到7颗水钻"},
                {"point_code": "STIGMA_CENTER_CHECK", "label": "花蕊居中检查", "method_hint": "defect_detection", "severity": "critical", "expected_value": "≤0.5 mm", "description": "默认阈值0.5mm", "pass_criteria": "花蕊偏移必须小于等于0.5mm（默认阈值）"},
                {"point_code": "STIGMA_OFFSET_CHECK", "label": "花蕊偏移检查", "method_hint": "defect_detection", "severity": "major", "pass_criteria": "不得偏离中心"},
            ],
            "questions": [{
                    "field": "cv_config.analyzers[1].name",
                    "question": "是否需要为花瓣、珍珠和水钻分别指定不同的分析器名称？",
            }],
        }
        return {"message": {"content": json.dumps(content, ensure_ascii=False)}}, 207400

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.author_text(
        message="花瓣数量必须为4；珍珠数量必须为3；水钻数量必须为7；花蕊必须居中。",
        language="zh-CN",
        current_sku={"item_number": "STAGE2-FLOWER-001"},
    )

    assert [item["point_code"] for item in result["checkpoints"]] == [
        "PETAL_COUNT_CHECK", "PEARL_COUNT_CHECK", "RHINESTONE_COUNT_CHECK", "STIGMA_CENTER_CHECK",
    ]
    by_code = {item["point_code"]: item for item in result["checkpoints"]}
    assert by_code["PETAL_COUNT_CHECK"]["method_hint"] == "counting"
    assert by_code["PETAL_COUNT_CHECK"]["expected_value"] == "4"
    assert by_code["PETAL_COUNT_CHECK"]["cv_config"] == {
        "analyzers": [{"name": "petal_segmentation", "params": {"backend": "silhouette"}}]
    }
    assert by_code["PEARL_COUNT_CHECK"]["expected_features"] == {"pearl_count": 3}
    assert by_code["PEARL_COUNT_CHECK"]["cv_config"] == {
        "analyzers": [{"name": "pearl_count", "params": {}}]
    }
    assert by_code["RHINESTONE_COUNT_CHECK"]["expected_value"] == "7"
    assert by_code["RHINESTONE_COUNT_CHECK"]["cv_config"] == {
        "analyzers": [{"name": "rhinestone_count", "params": {"backend": "socket_holes"}}]
    }
    assert by_code["STIGMA_CENTER_CHECK"]["method_hint"] == "alignment"
    assert by_code["STIGMA_CENTER_CHECK"]["cv_config"] == {
        "analyzers": [{"name": "pistil_localization", "params": {}}]
    }
    assert by_code["STIGMA_CENTER_CHECK"]["expected_value"] is None
    assert by_code["STIGMA_CENTER_CHECK"]["description"] is None
    assert by_code["STIGMA_CENTER_CHECK"]["pass_criteria"] is None
    assert "0.5" not in json.dumps(by_code["STIGMA_CENTER_CHECK"], ensure_ascii=False)
    assert result["questions"] == [{
        "field": "STIGMA_CENTER_CHECK.alignment_tolerance",
        "question": "请提供花蕊居中的最大允许偏移量（含单位）。",
    }]


def test_explicit_center_bound_from_administrator_is_authoritative():
    checkpoint = ai_gateway._validate_checkpoint({
        "point_code": "STAMEN_CENTER", "label": "花蕊居中",
        "method_hint": "alignment", "expected_value": "≤9 mm",
        "description": "模型声称9mm", "pass_criteria": "模型声称9mm",
    })
    result = ai_gateway._enforce_authoritative_text(
        [checkpoint], "花蕊必须居中，最大允许偏移不超过0.8毫米。"
    )
    assert result[0]["expected_value"] == "≤0.8 mm"
    assert result[0]["description"] is None
    assert result[0]["pass_criteria"] is None


def test_count_is_not_inferred_when_administrator_did_not_supply_one():
    checkpoint = ai_gateway._validate_checkpoint({
        "point_code": "PEARL_COUNT",
        "label": "珍珠数量",
        "method_hint": "counting",
        "pass_criteria": "数量必须符合确认值",
    })
    result = ai_gateway._enforce_authoritative_text([checkpoint], "请检查珍珠数量")
    assert result[0]["expected_value"] is None
    assert result[0]["cv_config"] == {}


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


def test_inspection_low_confidence_result_is_not_escalated_to_a_second_model(monkeypatch, tmp_path):
    """Qwen3-VL-4B is the sole production vision model — there is no 30B or
    remote escalation tier. A low-confidence result from the model is
    returned as-is (for the mandatory operator review downstream), not
    retried against a second, larger model."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")
    calls = []

    def fake_post(config, payload, path):
        calls.append(config.model)
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "SURFACE_DAMAGE",
                "result": "low_confidence",
                "confidence": 0.4,
                "observed_value": "unclear",
                "notes": "glare obscures the surface",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 120

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{"point_code": "SURFACE_DAMAGE", "label": "Surface damage", "method_hint": "defect_detection"}],
    )

    assert calls == ["local-4b"]
    assert result["checkpoint_results"][0]["result"] == "low_confidence"
    assert result["assistant"]["model"] == "local-4b"
    assert "fallback_used" not in result["assistant"]
    assert "routing" not in result


def test_process_card_image_ocr_preserves_numbers_units_and_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
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


def test_process_card_ocr_fails_closed_when_primary_errors(monkeypatch, tmp_path):
    """No fallback model exists to retry against — a primary transport/parse
    error propagates directly rather than being silently absorbed."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "card.png"
    image.write_bytes(b"card")

    def fake_post(config, payload, path):
        raise ai_gateway.StudioAIError("vision_assistant_timeout")

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    with pytest.raises(ai_gateway.StudioAIError, match="vision_assistant_timeout"):
        ai_gateway.extract_image_text(image_path=image, mime_type="image/png", language="en")


def test_cv_agreement_contradicting_observed_value_fails_closed(monkeypatch, tmp_path):
    """Audit 2026-07-22 §8.1: a live model claimed a CV count of 11 was
    "supported" while its own observed_value said 5 for the same point — an
    internally self-contradictory response. With no fallback model to
    retry against, the contradiction now fails closed directly instead of
    being accepted as a confident pass."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")

    def fake_post(config, payload, path):
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "PETAL_COUNT",
                "result": "pass",
                "confidence": 0.95,
                "observed_value": "5 petals visible",
                "notes": "matches standard",
                "cv_agreement": "agrees",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    with pytest.raises(ai_gateway.StudioAIError, match="vision_inspection_cv_agreement_contradicts_observed_value"):
        ai_gateway.inspect_image(
            image_path=image, mime_type="image/png", language="en",
            checkpoints=[{"point_code": "PETAL_COUNT", "label": "Petal count", "method_hint": "counting"}],
            cv_context={
                "schema_version": "1.0",
                "points": [{
                    "point_code": "PETAL_COUNT",
                    "analysis": {"analyzers": [{"analyzer": "petal_segmentation", "count": 11}]},
                }],
            },
        )


def test_cv_agreement_consistent_with_observed_value_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")
    calls = []

    def fake_post(config, payload, path):
        calls.append(config.model)
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "RHINESTONE_COUNT",
                "result": "pass",
                "confidence": 0.95,
                "observed_value": "7 rhinestones",
                "notes": "matches CV",
                "cv_agreement": "agrees",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{"point_code": "RHINESTONE_COUNT", "label": "Rhinestone count", "method_hint": "counting"}],
        cv_context={
            "schema_version": "1.0",
            "points": [{
                "point_code": "RHINESTONE_COUNT",
                "analysis": {"analyzers": [{"analyzer": "rhinestone_count", "count": 7}]},
            }],
        },
    )

    assert calls == ["local-4b"]
    assert result["checkpoint_results"][0]["result"] == "pass"


def test_cv_agreement_disagrees_on_non_counting_checkpoint_is_not_downgraded(monkeypatch, tmp_path):
    """The CV-authority downgrade rule (an honest 'disagrees' forcing
    low_confidence) is scoped to method_hint == 'counting'. A defect_detection
    checkpoint that happens to carry cv_context evidence and disagrees with
    it is left as the model reported it — that rule does not apply outside
    counting checkpoints."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")
    calls = []

    def fake_post(config, payload, path):
        calls.append(config.model)
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "SURFACE_CHECK",
                "result": "pass",
                "confidence": 0.95,
                "observed_value": "no visible defect",
                "notes": "CV evidence not applicable to this defect check",
                "cv_agreement": "disagrees",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{"point_code": "SURFACE_CHECK", "label": "Surface check", "method_hint": "defect_detection"}],
        cv_context={
            "schema_version": "1.0",
            "points": [{
                "point_code": "SURFACE_CHECK",
                "analysis": {"analyzers": [{"analyzer": "petal_segmentation", "count": 11}]},
            }],
        },
    )

    assert calls == ["local-4b"]
    assert result["checkpoint_results"][0]["result"] == "pass"


def test_counting_checkpoint_observed_value_is_always_sourced_from_cv(monkeypatch, tmp_path):
    """STAGE2_QWEN_VISION_PRODUCTION_ASSESSMENT_20260722: CV is the counting
    authority, not the vision model. Even when the model reports its own
    free-text observation, the recorded observed_value for a counting
    checkpoint with CV coverage must be the CV count, never the model's own
    tally."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")

    def fake_post(config, payload, path):
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "RHINESTONE_COUNT",
                "result": "pass",
                "confidence": 0.9,
                "observed_value": "looks about right",
                "notes": "matches CV",
                "cv_agreement": "agrees",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{
            "point_code": "RHINESTONE_COUNT", "label": "Rhinestone count",
            "method_hint": "counting",
        }],
        cv_context={
            "schema_version": "1.0",
            "points": [{
                "point_code": "RHINESTONE_COUNT",
                "analysis": {"analyzers": [{"analyzer": "rhinestone_count", "count": 7}]},
            }],
        },
    )

    assert result["checkpoint_results"][0]["observed_value"] == "7"
    assert result["checkpoint_results"][0]["result"] == "pass"


def test_counting_checkpoint_without_cv_detector_forces_low_confidence(monkeypatch, tmp_path):
    """A counting checkpoint with no configured CV detector can never be
    autonomously passed on the vision model's own guessed count — per the
    production assessment's root-cause finding (blind 30B/4B counting was
    wrong 2 times out of 3 with high stated confidence), it must always be
    forced to low_confidence so a human reviews it."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")

    def fake_post(config, payload, path):
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "BUTTON_COUNT",
                "result": "pass",
                "confidence": 0.97,
                "observed_value": "7 buttons",
                "notes": "counted directly",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{
            "point_code": "BUTTON_COUNT", "label": "Button count",
            "method_hint": "counting",
        }],
    )

    assert result["checkpoint_results"][0]["result"] == "low_confidence"
    assert "no_cv_detector_configured_for_counting_checkpoint" in result["checkpoint_results"][0]["notes"]


def test_counting_checkpoint_cv_disagreement_downgrades_to_low_confidence(monkeypatch, tmp_path):
    """An honest cv_agreement disagreement on a counting checkpoint is not
    silently accepted as a confident pass — CV being right is the default
    assumption for counting, so a dispute must route to a human rather than
    being resolved by trusting the vision model's own judgment."""
    monkeypatch.setenv("STUDIO_VISION_BASE_URL", "http://primary.invalid")
    monkeypatch.setenv("STUDIO_VISION_MODEL", "local-4b")
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")

    def fake_post(config, payload, path):
        value = {
            "summary": "review",
            "checkpoint_results": [{
                "point_code": "PEARL_COUNT",
                "result": "pass",
                "confidence": 0.9,
                "observed_value": "looks like a different count",
                "notes": "uncertain",
                "cv_agreement": "disagrees",
            }],
        }
        return {"choices": [{"message": {"content": json.dumps(value)}}]}, 100

    monkeypatch.setattr(ai_gateway, "_post", fake_post)
    result = ai_gateway.inspect_image(
        image_path=image, mime_type="image/png", language="en",
        checkpoints=[{
            "point_code": "PEARL_COUNT", "label": "Pearl count",
            "method_hint": "counting",
        }],
        cv_context={
            "schema_version": "1.0",
            "points": [{
                "point_code": "PEARL_COUNT",
                "analysis": {"analyzers": [{"analyzer": "pearl_count", "count": 3}]},
            }],
        },
    )

    assert result["checkpoint_results"][0]["result"] == "low_confidence"
    assert result["checkpoint_results"][0]["observed_value"] == "3"
    assert "model_disputes_cv_count_review_required" in result["checkpoint_results"][0]["notes"]
