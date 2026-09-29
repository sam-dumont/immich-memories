"""The full preparation reader and lean cut reader consume the same synthetic episode."""

from datetime import UTC, datetime, timedelta
from functools import partial

from immich_memories.analysis.annotation_lines import (
    AnnotationContract,
    AnnotationLineBatch,
    AssetAnnotationLine,
)
from immich_memories.analysis.editorial_text_gateway import SyncTextPromptRequester
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.analysis.selection_source_groups import project_episode_groups
from immich_memories.analysis.text_episode_reader import CachedTextEpisodeReader
from immich_memories.api.models import Asset, AssetType
from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.fixtures import scratch_store
from immich_memories.conformance.runtime import Case
from immich_memories.store.episode_readings import EpisodeReadingProducer, EpisodeReadingStore


class ChessAnnotations:
    """Synthetic prepared evidence supplied through the reader's annotation port."""

    def lines_for(self, asset_ids: tuple[str, ...]) -> AnnotationLineBatch:
        return AnnotationLineBatch(
            asset_ids,
            tuple(
                AssetAnnotationLine(
                    asset, "A chess tournament with players, chessboards and clocks."
                )
                for asset in asset_ids
            ),
            (),
            AnnotationContract("annotation-line-v1", ("synthetic-v1",)),
        )


def episode(llm: LLMConfig, *, lean: bool) -> str:
    start = datetime(2030, 6, 1, 12, tzinfo=UTC)
    assets = tuple(
        Asset(
            id=f"chess-{n}",
            type=AssetType.IMAGE,
            file_created_at=start + timedelta(minutes=n),
            file_modified_at=start,
            updated_at=start,
        )
        for n in range(2)
    )
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope()),
        EditorialDependencies(source_fetcher=lambda _: assets),
    )
    projections = project_episode_groups(prepared, tuple(asset.id for asset in assets))
    producer = EpisodeReadingProducer(
        llm.model, "conformance", "episode-reading-text-v1", "annotation-line-v1", ("synthetic-v1",)
    )
    requester = SyncTextPromptRequester(llm, max_tokens=16000, timeout_seconds=llm.timeout_seconds)
    with scratch_store() as (_, store):
        answer = CachedTextEpisodeReader(
            store=EpisodeReadingStore(store),
            producer=producer,
            annotations=ChessAnnotations(),
            requester=requester,
            lean=lean,
        ).read(projections)
    assert len(answer.episodes) == 1 and answer.episodes[0].reading is not None, (
        "episode returned no bankable reading"
    )
    reading = answer.episodes[0].reading
    assert "chess" in reading.what_happened.lower(), "episode reading lost the chess subject"
    assert set(reading.full_asset_ids) == {"chess-0", "chess-1"}, "episode lost source membership"
    assert reading.representatives, "episode returned no representative"
    return "chess episode preserves both source assets and a representative"


def episode_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return tuple(
        Case(
            name,
            partial(episode, llm, lean=lean),
            frozenset(
                {
                    "analysis.text_episode_reader:_read_missing",
                    "analysis.editorial_text_gateway:SyncTextPromptRequester._query",
                }
            ),
        )
        for name, lean in (("episode reading", False), ("lean episode reading", True))
    )
