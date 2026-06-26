"""Unit tests for QcResultParser — offline, no network/API dependency.

Branch coverage target: ≥90% of src/llm/result_parser.py.
"""
from __future__ import annotations

import pytest

from src.llm.result_parser import QcResultParser


class TestStripThinkingBlocks:
    def test_plain_text_unchanged(self):
        assert QcResultParser.strip_thinking_blocks("hello") == "hello"

    def test_single_think_block_removed(self):
        raw = "<think>some reasoning</think>result"
        assert QcResultParser.strip_thinking_blocks(raw) == "result"

    def test_multiline_think_block(self):
        raw = "<think>\nline1\nline2\n</think>\n{}"
        result = QcResultParser.strip_thinking_blocks(raw)
        assert "<think>" not in result
        assert "{}" in result

    def test_multiple_think_blocks(self):
        raw = "<think>first</think>middle<think>second</think>end"
        assert QcResultParser.strip_thinking_blocks(raw) == "middleend"

    def test_unclosed_think_not_consumed(self):
        # Regex requires closing tag; unclosed tag passes through
        raw = "<think>unclosed text"
        result = QcResultParser.strip_thinking_blocks(raw)
        assert "<think>" in result

    def test_empty_think_block(self):
        raw = "<think></think>result"
        assert QcResultParser.strip_thinking_blocks(raw) == "result"

    def test_empty_string(self):
        assert QcResultParser.strip_thinking_blocks("") == ""


class TestExtractJsonStr:
    def test_plain_json_object(self):
        text = '{"overall_result": "pass"}'
        assert QcResultParser.extract_json_str(text) == '{"overall_result": "pass"}'

    def test_markdown_fence_with_lang(self):
        text = '```json\n{"overall_result": "pass"}\n```'
        extracted = QcResultParser.extract_json_str(text)
        assert extracted == '{"overall_result": "pass"}'

    def test_markdown_fence_no_lang(self):
        text = '```\n{"k": "v"}\n```'
        result = QcResultParser.extract_json_str(text)
        assert result is not None and '"k"' in result

    def test_json_embedded_in_prose(self):
        text = 'Here is the result: {"overall_result": "pass"} done.'
        extracted = QcResultParser.extract_json_str(text)
        assert extracted is not None
        assert '"overall_result"' in extracted

    def test_no_json_returns_none(self):
        assert QcResultParser.extract_json_str("no json here") is None

    def test_only_closing_brace_returns_none(self):
        assert QcResultParser.extract_json_str("}") is None

    def test_chinese_text_before_json(self):
        text = '质检结果如下：\n{"overall_result":"pass","severity":"low"}'
        extracted = QcResultParser.extract_json_str(text)
        assert extracted is not None
        assert "overall_result" in extracted


class TestParseFullPipeline:
    def test_clean_pass_result(self):
        raw = '{"overall_result":"pass","similarity_score":0.95,"severity":"low","feedback_zh":"合格","feedback_en":"OK","deviations":[]}'
        result = QcResultParser.parse(raw)
        assert result["overall_result"] == "pass"
        assert result["severity"] == "low"
        assert result["deviations"] == []

    def test_think_block_stripped_before_parse(self):
        raw = '<think>let me reason...</think>{"overall_result":"reject","severity":"high","similarity_score":0.1,"feedback_zh":"划痕","feedback_en":"scratch","deviations":[]}'
        result = QcResultParser.parse(raw)
        assert result["overall_result"] == "reject"
        assert "error" not in result

    def test_markdown_fenced_json(self):
        raw = '```json\n{"overall_result":"needs_fix","severity":"medium","similarity_score":0.7,"feedback_zh":"需修","feedback_en":"fix","deviations":[]}\n```'
        result = QcResultParser.parse(raw)
        assert result["overall_result"] == "needs_fix"

    def test_empty_string_error(self):
        result = QcResultParser.parse("")
        assert result["overall_result"] == "unknown"
        assert result.get("error") == "empty_response"

    def test_whitespace_only_error(self):
        result = QcResultParser.parse("   \n  ")
        assert result["overall_result"] == "unknown"
        assert "error" in result

    def test_only_think_block_error(self):
        result = QcResultParser.parse("<think>just thinking</think>")
        assert result["overall_result"] == "unknown"
        assert "error" in result

    def test_invalid_overall_result_normalised(self):
        raw = '{"overall_result":"合格","severity":"low","similarity_score":0.9,"deviations":[]}'
        result = QcResultParser.parse(raw)
        assert result["overall_result"] == "unknown"
        assert result["_original_overall_result"] == "合格"

    def test_invalid_severity_normalised(self):
        raw = '{"overall_result":"pass","severity":"critical","similarity_score":0.9,"deviations":[]}'
        result = QcResultParser.parse(raw)
        assert result["severity"] == "unknown"

    def test_missing_deviations_defaults_to_list(self):
        raw = '{"overall_result":"pass","similarity_score":0.9,"severity":"low"}'
        result = QcResultParser.parse(raw)
        assert result["deviations"] == []

    def test_deviations_not_list_replaced(self):
        raw = '{"overall_result":"pass","severity":"low","similarity_score":0.9,"deviations":"none"}'
        result = QcResultParser.parse(raw)
        assert result["deviations"] == []

    def test_malformed_json_returns_error(self):
        result = QcResultParser.parse("{broken json !")
        assert result["overall_result"] == "unknown"
        assert "json_decode_error" in result.get("error", "")

    def test_json_array_not_dict_returns_error(self):
        result = QcResultParser.parse('[1, 2, 3]')
        assert result["overall_result"] == "unknown"
        assert "not_a_dict" in result.get("error", "")

    def test_chinese_english_mixed_feedback(self):
        raw = '{"overall_result":"needs_fix","severity":"medium","similarity_score":0.6,"feedback_zh":"产品有轻微划痕需修复","feedback_en":"Minor scratch detected","deviations":[{"field":"surface","expected":"smooth","actual":"scratched","severity":"medium"}]}'
        result = QcResultParser.parse(raw)
        assert result["overall_result"] == "needs_fix"
        assert "划痕" in result.get("feedback_zh", "")
        assert len(result["deviations"]) == 1

    def test_no_exception_ever_raised(self):
        bad_inputs = [
            "",
            "null",
            "[]",
            "<think>" * 100,
            '{"overall_result": null}',
            "```json\n```",
            "\x00\x01\x02",
            "x" * 10_000,
        ]
        for inp in bad_inputs:
            result = QcResultParser.parse(inp)
            assert isinstance(result, dict), f"Expected dict for input: {inp[:50]!r}"
            assert "overall_result" in result

    def test_all_valid_overall_results(self):
        for val in ("pass", "needs_fix", "reject", "unknown"):
            raw = f'{{"overall_result":"{val}","severity":"low","similarity_score":0.9,"deviations":[]}}'
            result = QcResultParser.parse(raw)
            assert result["overall_result"] == val

    def test_all_valid_severity_values(self):
        for val in ("low", "medium", "high", "unknown"):
            raw = f'{{"overall_result":"pass","severity":"{val}","similarity_score":0.9,"deviations":[]}}'
            result = QcResultParser.parse(raw)
            assert result["severity"] == val

    def test_think_block_with_prose_and_json(self):
        """Representative Qwen3 thinking output with prose before the JSON."""
        raw = (
            "<think>I need to check if the surface is scratched.\n"
            "The image shows a clear scratch.\n</think>\n"
            "Based on my analysis:\n"
            '{"overall_result":"reject","severity":"high","similarity_score":0.2,'
            '"feedback_zh":"有划痕","feedback_en":"scratch found","deviations":[]}'
        )
        result = QcResultParser.parse(raw)
        assert result["overall_result"] == "reject"
        assert result["severity"] == "high"
