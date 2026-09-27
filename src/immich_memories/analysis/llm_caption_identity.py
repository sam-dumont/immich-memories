"""Identity of opt-in image descriptions, independent of the SmolVLM bank."""

import hashlib
import json

from immich_memories.analysis.editorial_description_contract import (
    MAX_OUTPUT_TOKENS,
    PROMPT,
    RESPONSE_SCHEMA,
    TILE_VERSION,
)
from immich_memories.analysis.llm_providers import resolved_llm_config
from immich_memories.analysis.llm_text_identity import text_model_identity
from immich_memories.config_models_llm import LLMConfig

LLM_CAPTION_PREFIX = "llm-caption-v1@"
LLM_DESCRIPTION_SOURCE = "llm-envelope-v3-compact"


def llm_caption_identity(config: LLMConfig, artifact_id: str = "") -> str:
    """Key the image contract and effective model settings without retaining credentials."""
    material = {
        "model": text_model_identity(resolved_llm_config(config), thinking=False),
        "artifact": artifact_id,
        "prompt": PROMPT,
        "schema": RESPONSE_SCHEMA,
        "tile": TILE_VERSION,
        "detail": "high" if config.send_image_detail else None,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0.0,
        "require_complete": True,
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:24]
    return LLM_CAPTION_PREFIX + digest
