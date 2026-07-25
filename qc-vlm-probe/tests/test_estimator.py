"""Unit tests for lib/estimator.py's A2 smart_resize token estimator."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.estimator import DEFAULT_MAX_PIXELS, estimate_image_tokens


class TestEstimateImageTokens(unittest.TestCase):
    def test_1080p_reference_case(self):
        # PRD's worked example: a 1920x1080 frame at the Qwen3-VL default
        # config must estimate to exactly 2042 tokens.
        tokens, h_bar, w_bar = estimate_image_tokens(1920, 1080)
        self.assertEqual(tokens, 2042)
        self.assertEqual(h_bar, 1088)
        self.assertEqual(w_bar, 1920)

    def test_dimensions_are_multiples_of_factor(self):
        factor = 32
        for w, h in [(1920, 1080), (640, 480), (4000, 3000), (100, 100)]:
            _, h_bar, w_bar = estimate_image_tokens(w, h)
            self.assertEqual(h_bar % factor, 0)
            self.assertEqual(w_bar % factor, 0)

    def test_clamped_to_max_pixels(self):
        # A huge image must clamp down so h_bar * w_bar <= max_pixels.
        tokens, h_bar, w_bar = estimate_image_tokens(8000, 6000, max_pixels=DEFAULT_MAX_PIXELS)
        self.assertLessEqual(h_bar * w_bar, DEFAULT_MAX_PIXELS)

    def test_clamped_to_min_pixels(self):
        # A tiny image must be scaled up to at least min_pixels (4*factor^2).
        factor = 32
        min_pixels = 4 * factor * factor
        _, h_bar, w_bar = estimate_image_tokens(10, 10)
        self.assertGreaterEqual(h_bar * w_bar, min_pixels)

    def test_high_resolution_raises_ceiling(self):
        # With high_resolution=True, a large image should NOT be clamped down
        # to the default max_pixels -- the ceiling is 16384 * factor^2 instead.
        tokens_default, _, _ = estimate_image_tokens(8000, 6000)
        tokens_hires, _, _ = estimate_image_tokens(8000, 6000, high_resolution=True)
        self.assertGreater(tokens_hires, tokens_default)

    def test_non_perfect_square_token_pixels_rejected(self):
        with self.assertRaises(ValueError):
            estimate_image_tokens(100, 100, token_pixels=1000)

    def test_qwen25_vl_factor_28(self):
        # token_pixels=784 -> factor=28, per Qwen2.5-VL/QVQ convention.
        _, h_bar, w_bar = estimate_image_tokens(1920, 1080, token_pixels=784)
        self.assertEqual(h_bar % 28, 0)
        self.assertEqual(w_bar % 28, 0)


if __name__ == "__main__":
    unittest.main()
