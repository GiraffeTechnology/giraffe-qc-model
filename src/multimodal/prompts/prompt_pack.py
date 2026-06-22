"""PromptPack — assembles versioned prompts into MultimodalRequest messages."""
from __future__ import annotations

from src.multimodal.types import MultimodalMessagePart


def text_part(text: str) -> MultimodalMessagePart:
    return MultimodalMessagePart(type="text", text=text)


def image_path_part(path: str) -> MultimodalMessagePart:
    return MultimodalMessagePart(type="image", image_path=path)


def image_b64_part(b64: str) -> MultimodalMessagePart:
    return MultimodalMessagePart(type="image", image_base64=b64)
