"""Month and year accounts from two fictional, already prepared episodes."""

from datetime import UTC, datetime
from functools import partial

from immich_memories.analysis.catalogue_runtime import catalogue_requester
from immich_memories.analysis.library_catalogue import LibraryEpisode, build_catalogue
from immich_memories.config_loader import Config
from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.fixtures import scratch_store
from immich_memories.conformance.runtime import Case
from immich_memories.store.episode_readings import (
    BankedEpisodeReading,
    EpisodeReadingIdentity,
    EpisodeRepresentative,
)
from immich_memories.store.library_catalogue import CatalogueStore


def catalogue(llm: LLMConfig) -> str:
    events = tuple(
        LibraryEpisode(
            reading=BankedEpisodeReading(
                identity=EpisodeReadingIdentity(
                    f"episode-{month}-{day}", "synthetic", f"evidence-{month}-{day}"
                ),
                full_asset_ids=(f"asset-{month}-{day}",),
                what_happened=what,
                representatives=(
                    EpisodeRepresentative(f"asset-{month}-{day}", "Shows the occasion"),
                ),
                cull_decisions=(),
            ),
            taken_at=datetime(2030, month, day, tzinfo=UTC),
        )
        for month, what in (
            (6, "A chess tournament with chessboards and a trophy."),
            (7, "A sailing trip on a boat with sails."),
        )
        for day in (1, 2)
    )
    with scratch_store() as (_, store):
        answer = build_catalogue(
            events,
            store=CatalogueStore(store),
            requester=catalogue_requester(Config(tier="full", llm=llm)),
            producer="conformance",
        )
    assert "chess" in answer.months["2030-06"].account.lower(), "June account lost chess"
    assert "sail" in answer.months["2030-07"].account.lower(), "July account lost sailing"
    year = answer.years["2030"].account.lower()
    assert "chess" in year and "sail" in year, "year account omitted a month's evidence"
    return "both monthly subjects survive into the year account"


def catalogue_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case(
            "month and year catalogue",
            partial(catalogue, llm),
            frozenset(
                {
                    "analysis.library_catalogue:_AccountBuilder._ask",
                    "analysis.editorial_text_gateway:SyncTextPromptRequester._query",
                }
            ),
        ),
    )
