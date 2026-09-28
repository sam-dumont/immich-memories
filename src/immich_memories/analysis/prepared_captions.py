"""Read prepared captions for text consumers outside the selection reader."""

from __future__ import annotations

from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository


def prepared_captions(config: Config, asset_ids: tuple[str, ...]) -> dict[str, str]:
    """Read only the configured caption producer, in the caller's library store."""
    if not asset_ids:
        return {}
    editorial = config.editorial
    batch = AssetAnnotationFactRepository(
        open_store(config),
        description_model=editorial.description_model,
        head_versions=editorial.head_versions,
        pixel_producer_key=editorial.pixel_producer_key,
    ).facts_for(asset_ids)
    return {fact.asset_id: fact.description for fact in batch.facts if fact.description}
