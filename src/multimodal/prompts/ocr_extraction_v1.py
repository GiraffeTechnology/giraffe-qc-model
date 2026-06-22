"""OCR extraction prompt — version 1."""
from __future__ import annotations

VERSION = "ocr-extraction-v1"

SYSTEM_ROLE = (
    "You are an OCR extraction engine for product quality control. "
    "Read and extract text from product labels, tags, and markings."
)

SAFETY_RULES = (
    "Rules:\n"
    "- Only extract text that is clearly visible. Do not guess or invent text.\n"
    "- If confidence is low, include the text in issues list.\n"
    "- Return JSON only."
)

OUTPUT_SCHEMA = """{\n  \"detected_text\": [\"text1\", \"text2\"],\n  \"labels\": [{\"field\": \"serial_number\", \"value\": \"SN12345\", \"confidence\": 0.95}],\n  \"confidence\": 0.9,\n  \"issues\": [\"low_contrast_region\"]\n}"""

def build_prompt(expected_fields: list[str] | None = None) -> str:
    fields_hint = f"\nExpected fields: {', '.join(expected_fields)}." if expected_fields else ""
    return (
        f"{SYSTEM_ROLE}\n\n"
        f"Task: Extract all readable text from the product image.{fields_hint}\n\n"
        f"{SAFETY_RULES}\n\n"
        f"Output schema:\n{OUTPUT_SCHEMA}"
    )
