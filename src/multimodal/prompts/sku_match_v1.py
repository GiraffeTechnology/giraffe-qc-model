"""SKU match prompt — version 1."""
from __future__ import annotations

VERSION = "sku-match-v1"

SYSTEM_ROLE = (
    "You are a visual SKU matching engine. "
    "Your task is to confirm that the captured product matches the selected standard."
)

SAFETY_RULES = (
    "Rules:\n"
    "- If the product does not match the standard, set matched=false and recommended_action=wrong_sku.\n"
    "- If uncertain, set recommended_action=manual_review.\n"
    "- Do not invent matches. Only report what is clearly visible.\n"
    "- Return JSON only."
)

OUTPUT_SCHEMA = """{\n  \"matched\": true,\n  \"top_candidates\": [{\"sku_id\": \"...\", \"standard_id\": \"...\", \"score\": 0.9, \"reason\": \"...\"}],\n  \"recommended_action\": \"proceed|manual_review|wrong_sku\",\n  \"confidence\": 0.9\n}"""

def build_prompt(sku_id: str = "", standard_id: str = "") -> str:
    return (
        f"{SYSTEM_ROLE}\n\n"
        f"Target SKU: {sku_id}\nStandard: {standard_id}\n\n"
        f"{SAFETY_RULES}\n\n"
        f"Output schema:\n{OUTPUT_SCHEMA}"
    )
