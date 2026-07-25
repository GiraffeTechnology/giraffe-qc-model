#!/usr/bin/env python3
"""
lib/estimator.py — A2 local image-token estimator.

Mirrors the documented smart_resize logic: round each dimension to the
nearest multiple of the model's scaling factor, clamp the total pixel count
into [min_pixels, max_pixels], then tokens = h_bar * w_bar / token_pixels + 2
for the <vision_bos>/<vision_eos> pair.

This estimate exists solely to validate A2 (usage.image_tokens vs. the local
estimate). Its output must never enter a cost total -- cost is read from the
API's own `usage` object, never estimated (see lib/score.py).

Callable both as a library (estimate_image_tokens) and as a CLI, so
qc-probe.sh can shell out to a single implementation instead of duplicating
the arithmetic in a bash-embedded heredoc.

    python3 lib/estimator.py --image path.jpg --token-pixels 1024 \
        --max-pixels 2621440 [--high-resolution]
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

DEFAULT_MAX_PIXELS = 2_621_440  # 2560 * 32 * 32, Qwen3-VL / qwen3.x default
HIGH_RES_TOKEN_CEILING = 16384  # vl_high_resolution_images=true


def estimate_image_tokens(
    width: int,
    height: int,
    token_pixels: int = 1024,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    high_resolution: bool = False,
) -> tuple[int, int, int]:
    """Return (estimated_tokens, h_bar, w_bar) for one image.

    factor = sqrt(token_pixels): 32 for qwen3.7/3.6/3.5/Qwen3-VL/qwen-vl-max/
    qwen-vl-plus (token_pixels=1024), 28 for Qwen2.5-VL/QVQ (token_pixels=784).
    """
    factor = int(math.isqrt(token_pixels))
    if factor * factor != token_pixels:
        raise ValueError(f"token_pixels must be a perfect square, got {token_pixels}")

    h_bar = round(height / factor) * factor
    w_bar = round(width / factor) * factor

    min_pixels = 4 * factor * factor
    if high_resolution:
        max_pixels = HIGH_RES_TOKEN_CEILING * factor * factor

    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor

    tokens = int(h_bar * w_bar / token_pixels) + 2
    return tokens, h_bar, w_bar


def estimate_image_tokens_for_file(
    image_path: Path,
    token_pixels: int = 1024,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    high_resolution: bool = False,
) -> tuple[int, int, int]:
    from PIL import Image  # lazy: only the CLI/file path needs Pillow

    with Image.open(image_path) as im:
        width, height = im.width, im.height
    return estimate_image_tokens(width, height, token_pixels, max_pixels, high_resolution)


def main() -> int:
    ap = argparse.ArgumentParser(description="A2 image-token estimator (smart_resize)")
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--token-pixels", type=int, default=1024)
    ap.add_argument("--max-pixels", type=int, default=DEFAULT_MAX_PIXELS)
    ap.add_argument("--high-resolution", action="store_true")
    args = ap.parse_args()

    tokens, h_bar, w_bar = estimate_image_tokens_for_file(
        args.image, args.token_pixels, args.max_pixels, args.high_resolution
    )
    print(f"{tokens} {h_bar} {w_bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
