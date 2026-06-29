"""Generate the artificial jewelry flower brooch QC simulation dataset.

This script uses only Python standard-library code so the generated dataset is
not coupled to Pillow, OpenCV, Pad, MNN, DashScope, or production QC routing.
"""
from __future__ import annotations

import json
import shutil
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("data/qc_simulation/artificial_jewelry_flower_brooch")
SEED_IMAGE = ROOT / "seed" / "standard" / "seed_standard_001.png"
CAPTURED_AT = datetime(2026, 6, 29, tzinfo=timezone.utc).isoformat()
SKU_ID = "artificial_jewelry_flower_brooch_001"
SKU_NAME = "Artificial jewelry flower brooch / hair clip"
SOURCE_URL = "https://susangloriaboutique.com/products/blush-pearl-bloom-brooch"
IMAGE_URL = "https://susangloriaboutique.com/cdn/shop/files/1777275268018-8mlmqbp6qz3_1024x1024.png?v=1779955515"
LICENSE_NOTE = "public_product_page_internal_test_only"
OPERATOR_PROVIDED_NOTE = "operator_provided_real_production_photo_internal_test_only"
REAL_STANDARD_IMAGE = ROOT / "real" / "standard" / "real_production_standard_001.jpg"
REAL_CENTER_OFFCENTER_IMAGE = (
    ROOT / "real" / "fail_center_offcenter" / "real_production_center_offcenter_001.jpg"
)

POINTS = (
    "center_alignment",
    "rhinestone_count",
    "pearl_count",
    "pearl_surface_integrity",
    "petal_integrity",
    "incidental_abnormality",
)
SYNTHETIC_MAX_DIM = 384


def _read_chunks(path: Path):
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"{path} is not a PNG")
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        yield chunk_type, chunk_data
        offset += 12 + length


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_png(path: Path) -> tuple[int, int, list[list[tuple[int, int, int]]]]:
    width = height = bit_depth = color_type = interlace = None
    palette: list[tuple[int, int, int]] = []
    compressed = bytearray()

    for chunk_type, chunk_data in _read_chunks(path):
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"PLTE":
            palette = [
                tuple(chunk_data[i:i + 3])  # type: ignore[arg-type]
                for i in range(0, len(chunk_data), 3)
            ]
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)

    if width is None or height is None or bit_depth is None or color_type is None or interlace is None:
        raise ValueError(f"{path} is missing IHDR")
    if bit_depth != 8 or interlace != 0:
        raise ValueError(f"{path} must be an 8-bit non-interlaced PNG")

    if color_type == 2:
        channels = 3
    elif color_type == 3:
        channels = 1
    elif color_type == 6:
        channels = 4
    else:
        raise ValueError(f"Unsupported PNG color_type={color_type}")

    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    rows: list[bytearray] = []
    pos = 0
    prev = bytearray(stride)
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        scanline = bytearray(raw[pos:pos + stride])
        pos += stride
        for i in range(stride):
            left = scanline[i - channels] if i >= channels else 0
            up = prev[i]
            upper_left = prev[i - channels] if i >= channels else 0
            if filter_type == 1:
                scanline[i] = (scanline[i] + left) & 0xFF
            elif filter_type == 2:
                scanline[i] = (scanline[i] + up) & 0xFF
            elif filter_type == 3:
                scanline[i] = (scanline[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                scanline[i] = (scanline[i] + _paeth(left, up, upper_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError(f"Unsupported PNG filter={filter_type}")
        rows.append(scanline)
        prev = scanline

    rgb_rows: list[list[tuple[int, int, int]]] = []
    for row in rows:
        rgb_row: list[tuple[int, int, int]] = []
        if color_type == 3:
            for idx in row:
                rgb_row.append(palette[idx])
        elif color_type == 2:
            for i in range(0, len(row), 3):
                rgb_row.append((row[i], row[i + 1], row[i + 2]))
        else:
            for i in range(0, len(row), 4):
                alpha = row[i + 3] / 255
                rgb_row.append((
                    int(row[i] * alpha + 255 * (1 - alpha)),
                    int(row[i + 1] * alpha + 255 * (1 - alpha)),
                    int(row[i + 2] * alpha + 255 * (1 - alpha)),
                ))
        rgb_rows.append(rgb_row)
    return width, height, rgb_rows


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def write_png(path: Path, width: int, height: int, rows: list[list[tuple[int, int, int]]]) -> None:
    payload = bytearray()
    for row in rows:
        payload.append(0)
        for r, g, b in row:
            payload.extend((max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))))
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    png.extend(_chunk(b"IDAT", zlib.compress(bytes(payload), level=6)))
    png.extend(_chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(png))


def copy_rows(rows: list[list[tuple[int, int, int]]]) -> list[list[tuple[int, int, int]]]:
    return [list(row) for row in rows]


def downsample(
    width: int,
    height: int,
    rows: list[list[tuple[int, int, int]]],
    max_dim: int,
) -> tuple[int, int, list[list[tuple[int, int, int]]]]:
    scale = min(max_dim / width, max_dim / height, 1.0)
    if scale == 1.0:
        return width, height, rows
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    sampled: list[list[tuple[int, int, int]]] = []
    for y in range(new_height):
        src_y = min(height - 1, int(y / scale))
        sampled_row: list[tuple[int, int, int]] = []
        for x in range(new_width):
            src_x = min(width - 1, int(x / scale))
            sampled_row.append(rows[src_y][src_x])
        sampled.append(sampled_row)
    return new_width, new_height, sampled


def blend(rows, x: int, y: int, color: tuple[int, int, int], alpha: float) -> None:
    if y < 0 or y >= len(rows) or x < 0 or x >= len(rows[0]):
        return
    old = rows[y][x]
    rows[y][x] = tuple(int(old[i] * (1 - alpha) + color[i] * alpha) for i in range(3))


def circle(rows, cx: int, cy: int, radius: int, color: tuple[int, int, int], alpha: float) -> None:
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                blend(rows, x, y, color, alpha)


def line(rows, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int], alpha: float) -> None:
    steps = max(abs(x2 - x1), abs(y2 - y1), 1)
    for step in range(steps + 1):
        t = step / steps
        x = round(x1 + (x2 - x1) * t)
        y = round(y1 + (y2 - y1) * t)
        for oy in (-1, 0, 1):
            blend(rows, x, y + oy, color, alpha)


def local_noise(rows, cx: int, cy: int, index: int, radius: int = 8, strength: int = 5) -> None:
    """Apply subtle deterministic texture so samples are visibly but gently distinct."""
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if y < 0 or y >= len(rows) or x < 0 or x >= len(rows[0]):
                continue
            if (x - cx) ** 2 + (y - cy) ** 2 > radius ** 2:
                continue
            if ((x * 17 + y * 31 + index * 13) % 7) not in (0, 3):
                continue
            old = rows[y][x]
            delta = ((x * 5 + y * 3 + index * 11) % (strength * 2 + 1)) - strength
            rows[y][x] = tuple(max(0, min(255, channel + delta)) for channel in old)


def apply_defect(rows, width: int, height: int, defect_type: str, index: int) -> None:
    idx = index - 1
    dx = [-6, -4, -2, 1, 3, 5, -5, -1, 2, 6][idx]
    dy = [-3, 2, -5, 4, -1, 3, 5, -2, 1, -4][idx]
    radius_delta = [0, 1, -1, 2, -2, 1, 0, -1, 2, -2][idx]
    alpha_delta = [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, -0.015, 0.015, 0.025][idx]
    angle_delta = [-12, -8, -5, -2, 2, 5, 8, 11, -10, 7][idx]
    cx = width // 2
    cy = height // 2
    if defect_type == "pass":
        px = int(width * (0.49 + idx * 0.006))
        py = int(height * (0.49 + ((idx % 4) - 1.5) * 0.006))
        circle(rows, px, py, 3 + (idx % 3), (255, 244, 225), 0.045 + (idx % 4) * 0.01)
        local_noise(rows, px + dx, py + dy, index, radius=5 + idx % 4, strength=2)
    elif defect_type == "center_alignment":
        circle(rows, cx + dx // 2, cy + dy // 2, 22 + radius_delta, (250, 235, 220), 0.13 + alpha_delta / 2)
        circle(rows, cx + 14 + dx, cy - 8 + dy, 15 + (idx % 4), (174, 122, 83), 0.17 + alpha_delta)
        local_noise(rows, cx + 14 + dx, cy - 8 + dy, index, radius=7 + idx % 5, strength=3)
    elif defect_type == "rhinestone_count":
        anchors = [
            (0.62, 0.40), (0.59, 0.36), (0.54, 0.34), (0.46, 0.38), (0.42, 0.45),
            (0.44, 0.54), (0.50, 0.60), (0.57, 0.58), (0.64, 0.51), (0.61, 0.45),
        ]
        rx = int(width * anchors[idx][0]) + dx // 2
        ry = int(height * anchors[idx][1]) + dy // 2
        circle(rows, rx, ry, 7 + (idx % 4), (92, 74, 66), 0.45 + max(alpha_delta, -0.01))
        circle(rows, rx, ry, 4 + (idx % 3), (34, 30, 28), 0.18 + (idx % 3) * 0.02)
        local_noise(rows, rx, ry, index, radius=5 + idx % 4, strength=4)
    elif defect_type == "pearl_surface_integrity":
        px = int(width * (0.50 + (idx % 5) * 0.018)) + dx // 2
        py = int(height * (0.40 + (idx // 5) * 0.09)) + dy // 2
        length = 22 + (idx % 5) * 3
        rise = int((length * angle_delta) / 24)
        line(rows, px - length // 2, py - rise // 2, px + length // 2, py + rise // 2, (92, 82, 78), 0.42 + (idx % 4) * 0.035)
        line(rows, px - length // 2 + 2, py - rise // 2 + 2, px + length // 2 - 3, py + rise // 2 + 3, (245, 245, 240), 0.12 + (idx % 3) * 0.02)
        local_noise(rows, px, py, index, radius=6 + idx % 4, strength=3)
    elif defect_type == "pearl_count":
        anchors = [
            (0.44, 0.48), (0.50, 0.42), (0.56, 0.48), (0.48, 0.57), (0.58, 0.57),
            (0.43, 0.55), (0.53, 0.52), (0.61, 0.49), (0.47, 0.44), (0.55, 0.60),
        ]
        px = int(width * anchors[idx][0]) + dx // 3
        py = int(height * anchors[idx][1]) + dy // 3
        circle(rows, px, py, 13 + (idx % 5), (188, 151, 112), 0.32 + (idx % 4) * 0.025)
        circle(rows, px, py, 7 + (idx % 4), (105, 79, 61), 0.16 + (idx % 3) * 0.025)
        local_noise(rows, px, py, index, radius=7 + idx % 5, strength=3)
    elif defect_type == "petal_integrity":
        anchors = [
            (0.70, 0.31), (0.73, 0.36), (0.68, 0.66), (0.62, 0.72), (0.34, 0.68),
            (0.30, 0.55), (0.32, 0.39), (0.41, 0.31), (0.58, 0.29), (0.76, 0.52),
        ]
        px = int(width * anchors[idx][0]) + dx // 2
        py = int(height * anchors[idx][1]) + dy // 2
        chip_radius = 9 + (idx % 5)
        circle(rows, px, py, chip_radius, (255, 255, 255), 0.46 + (idx % 4) * 0.035)
        line(rows, px - chip_radius, py + 5 + dy // 4, px + chip_radius + 2, py - 5 + angle_delta // 5, (210, 198, 190), 0.34 + (idx % 4) * 0.035)
        local_noise(rows, px, py, index, radius=6 + idx % 5, strength=4)
    elif defect_type == "mixed_defects":
        apply_defect(rows, width, height, "rhinestone_count", index)
        apply_defect(rows, width, height, "petal_integrity", 10 - idx)
        circle(rows, int(width * (0.56 + idx * 0.008)), int(height * (0.53 + ((idx % 3) - 1) * 0.018)), 8 + idx % 5, (210, 184, 112), 0.18 + (idx % 4) * 0.025)
        local_noise(rows, int(width * 0.58) + dx, int(height * 0.55) + dy, index, radius=8 + idx % 4, strength=4)
    else:
        raise ValueError(defect_type)


def checkpoint_results_for(defect_type: str) -> list[dict[str, str]]:
    results = {point: "pass" for point in POINTS}
    if defect_type == "center_alignment":
        results["center_alignment"] = "fail"
    elif defect_type == "rhinestone_count":
        results["rhinestone_count"] = "fail"
    elif defect_type == "pearl_surface_integrity":
        results["pearl_surface_integrity"] = "fail"
    elif defect_type == "pearl_count":
        results["pearl_count"] = "fail"
    elif defect_type == "petal_integrity":
        results["petal_integrity"] = "fail"
    elif defect_type == "mixed_defects":
        results["rhinestone_count"] = "fail"
        results["petal_integrity"] = "fail"
        results["incidental_abnormality"] = "fail"
    return [{"code": code, "result": result} for code, result in results.items()]


def defects_for(defect_type: str) -> list[dict[str, str]]:
    if defect_type == "pass":
        return []
    details = {
        "center_alignment": (
            "center_alignment",
            "major",
            "Central stamen cluster is subtly shifted from petal center beyond tolerance.",
        ),
        "rhinestone_count": (
            "rhinestone_count",
            "critical",
            "One tiny rhinestone is missing, leaving a dark empty rose-gold setting.",
        ),
        "pearl_surface_integrity": (
            "pearl_surface_integrity",
            "major",
            "One pearl contains a fine hairline crack that is visible at inspection distance.",
        ),
        "pearl_count": (
            "pearl_count",
            "critical",
            "One pearl bead is missing from the expected cluster.",
        ),
        "petal_integrity": (
            "petal_integrity",
            "major",
            "A petal edge contains a small chip / micro-crack.",
        ),
    }
    if defect_type == "mixed_defects":
        return [
            {
                "code": "rhinestone_count",
                "expected_result": "fail",
                "severity": "critical",
                "description": details["rhinestone_count"][2],
            },
            {
                "code": "petal_integrity",
                "expected_result": "fail",
                "severity": "major",
                "description": details["petal_integrity"][2],
            },
            {
                "code": "incidental_abnormality",
                "expected_result": "fail",
                "severity": "major",
                "description": "Slight abnormal pearl discoloration is visible near the stamen cluster.",
            },
        ]
    code, severity, description = details[defect_type]
    return [
        {
            "code": code,
            "expected_result": "fail",
            "severity": severity,
            "description": description,
        }
    ]


def real_production_rows() -> tuple[list[dict], list[dict]]:
    metadata_rows: list[dict] = []
    label_rows: list[dict] = []
    if REAL_STANDARD_IMAGE.exists():
        metadata_rows.append(
            {
                "sample_id": "real_production_standard_001",
                "image_path": str(REAL_STANDARD_IMAGE),
                "source_platform": "operator-provided real production photo",
                "captured_at": CAPTURED_AT,
                "sku_name": SKU_NAME,
                "image_role": "real_production_standard",
                "is_synthetic": False,
                "license_note": OPERATOR_PROVIDED_NOTE,
            }
        )
        label_rows.append(
            {
                "sample_id": "real_production_standard_001",
                "sku_id": SKU_ID,
                "image_path": str(REAL_STANDARD_IMAGE),
                "based_on_seed": "real_production_standard_001",
                "is_synthetic": False,
                "expected_final_result": "pass",
                "defects": [],
                "expected_checkpoint_results": checkpoint_results_for("pass"),
            }
        )
    if REAL_CENTER_OFFCENTER_IMAGE.exists():
        metadata_rows.append(
            {
                "sample_id": "real_production_center_offcenter_001",
                "image_path": str(REAL_CENTER_OFFCENTER_IMAGE),
                "source_platform": "operator-provided real production photo",
                "captured_at": CAPTURED_AT,
                "sku_name": SKU_NAME,
                "image_role": "real_production_fail_center_offcenter",
                "is_synthetic": False,
                "license_note": OPERATOR_PROVIDED_NOTE,
            }
        )
        label_rows.append(
            {
                "sample_id": "real_production_center_offcenter_001",
                "sku_id": SKU_ID,
                "image_path": str(REAL_CENTER_OFFCENTER_IMAGE),
                "based_on_seed": "real_production_standard_001",
                "is_synthetic": False,
                "expected_final_result": "fail",
                "defects": [
                    {
                        "code": "center_alignment",
                        "expected_result": "fail",
                        "severity": "major",
                        "description": (
                            "Real production defect: the flower heart / stamen cluster is visibly "
                            "shifted off the four-petal center."
                        ),
                    }
                ],
                "expected_checkpoint_results": checkpoint_results_for("center_alignment"),
            }
        )
    return metadata_rows, label_rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            fh.write("\n")


def main() -> None:
    width, height, seed_rows = read_png(SEED_IMAGE)
    width, height, seed_rows = downsample(width, height, seed_rows, SYNTHETIC_MAX_DIM)
    source_rows = [
        {
            "sample_id": "seed_standard_001",
            "image_path": str(SEED_IMAGE),
            "source_url": SOURCE_URL,
            "source_image_url": IMAGE_URL,
            "source_platform": "Susan & Gloria Boutique Shopify product page",
            "captured_at": CAPTURED_AT,
            "sku_name": SKU_NAME,
            "image_role": "standard",
            "license_note": LICENSE_NOTE,
        }
    ]

    seed_pass = ROOT / "seed" / "pass" / "seed_pass_001.png"
    shutil.copyfile(SEED_IMAGE, seed_pass)
    source_rows.append(
        {
            "sample_id": "seed_pass_001",
            "image_path": str(seed_pass),
            "source_url": SOURCE_URL,
            "source_image_url": IMAGE_URL,
            "source_platform": "Susan & Gloria Boutique Shopify product page",
            "captured_at": CAPTURED_AT,
            "sku_name": SKU_NAME,
            "image_role": "pass_reference",
            "license_note": LICENSE_NOTE,
        }
    )

    categories = [
        ("pass", "synthetic/pass", "sim_pass"),
        ("center_alignment", "synthetic/fail_center_offcenter_subtle", "sim_center_offcenter"),
        ("rhinestone_count", "synthetic/fail_missing_rhinestone_subtle", "sim_missing_rhinestone"),
        ("pearl_surface_integrity", "synthetic/fail_pearl_hairline_crack", "sim_pearl_hairline_crack"),
        ("pearl_count", "synthetic/fail_missing_pearl", "sim_missing_pearl"),
        ("petal_integrity", "synthetic/fail_petal_micro_chip", "sim_petal_micro_chip"),
        ("mixed_defects", "synthetic/mixed_defects", "sim_mixed_defects"),
    ]

    metadata_rows: list[dict] = []
    label_rows: list[dict] = []
    for defect_type, directory, prefix in categories:
        for idx in range(1, 11):
            sample_id = f"{prefix}_{idx:03d}"
            output_path = ROOT / directory / f"{sample_id}.png"
            rows = copy_rows(seed_rows)
            apply_defect(rows, width, height, defect_type, idx)
            write_png(output_path, width, height, rows)
            metadata_rows.append(
                {
                    "sample_id": sample_id,
                    "image_path": str(output_path),
                    "based_on_seed": "seed_standard_001",
                    "is_synthetic": True,
                    "synthetic_defect_type": defect_type,
                    "subtlety": "subtle",
                    "generation_method": "standard-library pixel overlay on public product seed image",
                    "source_seed_url": SOURCE_URL,
                    "license_note": LICENSE_NOTE,
                }
            )
            checkpoints = checkpoint_results_for(defect_type)
            label_rows.append(
                {
                    "sample_id": sample_id,
                    "sku_id": SKU_ID,
                    "image_path": str(output_path),
                    "based_on_seed": "seed_standard_001",
                    "is_synthetic": True,
                    "expected_final_result": "pass" if defect_type == "pass" else "fail",
                    "defects": defects_for(defect_type),
                    "expected_checkpoint_results": checkpoints,
                }
            )

    real_metadata_rows, real_label_rows = real_production_rows()
    label_rows.extend(real_label_rows)

    write_jsonl(ROOT / "seed" / "source_metadata.jsonl", source_rows)
    write_jsonl(ROOT / "synthetic" / "synthetic_metadata.jsonl", metadata_rows)
    write_jsonl(ROOT / "real" / "real_metadata.jsonl", real_metadata_rows)
    write_jsonl(ROOT / "labels" / "expected_results.jsonl", label_rows)


if __name__ == "__main__":
    main()
