"""Generate synthetic PNG test fixtures for giraffe-qc-model.

Run once before executing tests that need image files:
  python scripts/generate_test_fixtures.py

Output: tests/fixtures/{good,defect_scratch,defect_dent,defect_missing_part,ambiguous,hard}/

The generated images are intentionally simple geometric shapes to keep
the repository lightweight. Replace with real product photos for higher
fidelity cloud/device tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

try:
    import cv2
    import numpy as np
except ImportError:
    print("Requires opencv-python-headless + numpy. Install: pip install -e '.[dev]'")
    sys.exit(1)


def _make_dir(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(path: Path, img: np.ndarray) -> None:
    cv2.imwrite(str(path), img)
    print(f"  {path.relative_to(ROOT)}")


def _clean_product(h: int = 480, w: int = 640) -> np.ndarray:
    """Grey rectangle on light background — clean reference."""
    img = np.full((h, w, 3), 240, dtype=np.uint8)
    cv2.rectangle(img, (80, 60), (w - 80, h - 60), (160, 160, 160), -1)
    return img


def _scratch(h: int = 480, w: int = 640) -> np.ndarray:
    img = _clean_product(h, w)
    cv2.line(img, (120, 200), (400, 280), (40, 40, 40), 3)
    return img


def _dent(h: int = 480, w: int = 640) -> np.ndarray:
    img = _clean_product(h, w)
    cv2.ellipse(img, (320, 240), (45, 22), 30, 0, 360, (70, 70, 70), -1)
    return img


def _missing_part(h: int = 480, w: int = 640) -> np.ndarray:
    img = _clean_product(h, w)
    # Erase a rectangular region to simulate missing component
    cv2.rectangle(img, (400, 100), (560, 200), (240, 240, 240), -1)
    return img


def _slight_mark(h: int = 480, w: int = 640) -> np.ndarray:
    img = _clean_product(h, w)
    cv2.line(img, (200, 200), (260, 225), (135, 135, 135), 1)
    return img


def _dark(h: int = 480, w: int = 640) -> np.ndarray:
    img = _clean_product(h, w)
    return (img.astype(np.float32) * 0.20).clip(0, 255).astype(np.uint8)


def main() -> None:
    print("Generating synthetic test fixtures...")

    _save(_make_dir(FIXTURES / "good") / "product_ok.png", _clean_product())
    _save(_make_dir(FIXTURES / "defect_scratch") / "scratch_01.png", _scratch())
    _save(_make_dir(FIXTURES / "defect_dent") / "dent_01.png", _dent())
    _save(_make_dir(FIXTURES / "defect_missing_part") / "missing_01.png", _missing_part())
    _save(_make_dir(FIXTURES / "ambiguous") / "slight_mark_01.png", _slight_mark())
    _save(_make_dir(FIXTURES / "hard") / "dark_01.png", _dark())

    count = len(list(FIXTURES.rglob("*.png")))
    print(f"\nDone. {count} PNG files in tests/fixtures/")
    print("Replace with real product photos for higher-fidelity cloud/device tests.")


if __name__ == "__main__":
    main()
