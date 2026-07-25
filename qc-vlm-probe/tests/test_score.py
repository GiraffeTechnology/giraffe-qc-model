"""Unit tests for lib/score.py: tiered pricing, Wilson intervals, and the
corrupted-response-must-not-crash contract for the raw-response parser."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.score import build_rows, extract_model_json, tier_rate, wilson


class TestWilson(unittest.TestCase):
    def test_zero_n_returns_full_width_interval(self):
        p, lo, hi = wilson(0, 0)
        self.assertEqual((p, lo, hi), (0.0, 0.0, 1.0))

    def test_perfect_score_upper_bound_below_one(self):
        # 30/30 correct: point estimate is 1.0 but the CI must stay < 1.0 --
        # this is exactly why verdict_for() gates on ci_high, not the point.
        p, lo, hi = wilson(30, 30)
        self.assertEqual(p, 1.0)
        self.assertLess(hi, 1.0)
        self.assertGreater(lo, 0.0)

    def test_interval_stays_within_unit_range(self):
        for successes, n in [(0, 5), (5, 5), (3, 10), (1, 1)]:
            _, lo, hi = wilson(successes, n)
            self.assertGreaterEqual(lo, 0.0)
            self.assertLessEqual(hi, 1.0)
            self.assertLessEqual(lo, hi)

    def test_more_samples_narrows_interval_at_same_rate(self):
        _, lo_small, hi_small = wilson(5, 10)
        _, lo_big, hi_big = wilson(50, 100)
        self.assertLess(hi_big - lo_big, hi_small - lo_small)


class TestTierRate(unittest.TestCase):
    def test_single_tier(self):
        self.assertEqual(tier_rate([(0, 2.0)], 5), 2.0)
        self.assertEqual(tier_rate([(0, 2.0)], 1_000_000), 2.0)

    def test_tiered_bills_all_tokens_at_matched_tier(self):
        tiers = [(0, 2.0), (256000, 6.0)]
        # Below the threshold: base rate.
        self.assertEqual(tier_rate(tiers, 100_000), 2.0)
        # At or above the threshold: the request is billed ENTIRELY at the
        # higher tier's rate, not just the tokens over the line.
        self.assertEqual(tier_rate(tiers, 256_000), 6.0)
        self.assertEqual(tier_rate(tiers, 400_000), 6.0)

    def test_three_tiers_picks_highest_applicable(self):
        tiers = [(0, 1.0), (100, 2.0), (200, 3.0)]
        self.assertEqual(tier_rate(tiers, 150), 2.0)
        self.assertEqual(tier_rate(tiers, 250), 3.0)


class TestExtractModelJson(unittest.TestCase):
    def test_plain_json_content(self):
        raw = {"choices": [{"message": {"content": '{"verdict": "accept"}'}}]}
        pred, err = extract_model_json(raw)
        self.assertEqual(pred, {"verdict": "accept"})
        self.assertIsNone(err)

    def test_fenced_json_content(self):
        raw = {"choices": [{"message": {"content": '```json\n{"verdict": "reject"}\n```'}}]}
        pred, err = extract_model_json(raw)
        self.assertEqual(pred, {"verdict": "reject"})
        self.assertIsNone(err)

    def test_prose_wrapped_json(self):
        raw = {"choices": [{"message": {
            "content": 'Sure, here is the result:\n{"verdict": "accept"}\nLet me know if you need more.'
        }}]}
        pred, err = extract_model_json(raw)
        self.assertEqual(pred, {"verdict": "accept"})

    def test_missing_choices_does_not_crash(self):
        pred, err = extract_model_json({"error": {"code": "InvalidParameter"}})
        self.assertIsNone(pred)
        self.assertEqual(err, "no_content")

    def test_unparseable_json_does_not_crash(self):
        raw = {"choices": [{"message": {"content": "{not valid json at all}"}}]}
        pred, err = extract_model_json(raw)
        self.assertIsNone(pred)
        self.assertTrue(err.startswith("json_decode"))

    def test_no_braces_at_all_does_not_crash(self):
        raw = {"choices": [{"message": {"content": "the model refused to answer"}}]}
        pred, err = extract_model_json(raw)
        self.assertIsNone(pred)
        self.assertEqual(err, "no_json_object")

    def test_list_content_parts_joined(self):
        raw = {"choices": [{"message": {"content": [
            {"text": '{"verdict"'}, {"text": ': "accept"}'},
        ]}}]}
        pred, err = extract_model_json(raw)
        self.assertEqual(pred, {"verdict": "accept"})


class TestBuildRowsCorruptedResponses(unittest.TestCase):
    """The scorer must degrade gracefully -- a bad raw file becomes a row with
    parse_ok=False and an error string, never an exception that kills the run.
    """

    def _write(self, raw_dir: Path, name: str, content: str):
        (raw_dir / name).write_text(content, encoding="utf-8")

    def test_truncated_json_file(self):
        with tempfile.TemporaryDirectory() as td:
            raw_dir = Path(td)
            self._write(raw_dir, "sample001__qwen3-vl-235b-a22b-instruct.json",
                        '{"choices": [{"message": {"content": "{\\"verdict\\"')
            rows = build_rows(raw_dir, truth={}, specs={})
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0].parse_ok)
            self.assertIsNotNone(rows[0].error)

    def test_valid_envelope_missing_choices(self):
        with tempfile.TemporaryDirectory() as td:
            raw_dir = Path(td)
            self._write(raw_dir, "sample002__qwen3-vl-235b-a22b-instruct.json",
                        json.dumps({"error": {"code": "NotFound", "message": "no such model"}}))
            rows = build_rows(raw_dir, truth={}, specs={})
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0].parse_ok)
            self.assertEqual(rows[0].http_error, "NotFound")
            self.assertEqual(rows[0].error, "no_content")

    def test_well_formed_response_scores_correctly(self):
        with tempfile.TemporaryDirectory() as td:
            raw_dir = Path(td)
            body = {
                "choices": [{"message": {"content": json.dumps({
                    "petals": 6, "pearls": 4, "rhinestones": 2,
                    "verdict": "accept", "confidence": 0.9,
                    "needs_human_review": False,
                })}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "image_tokens": 900},
            }
            self._write(raw_dir, "sample003__qwen3-vl-235b-a22b-instruct.json", json.dumps(body))
            truth = {"sample003": {"petals": 6, "pearls": 4, "rhinestones": 2, "verdict": "accept"}}
            rows = build_rows(raw_dir, truth=truth, specs={})
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertTrue(row.parse_ok)
            self.assertTrue(row.verdict_correct)
            self.assertFalse(row.false_accept)
            self.assertFalse(row.false_reject)

    def test_ignores_files_without_double_underscore(self):
        with tempfile.TemporaryDirectory() as td:
            raw_dir = Path(td)
            self._write(raw_dir, "not-a-cell-file.json", "{}")
            rows = build_rows(raw_dir, truth={}, specs={})
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
