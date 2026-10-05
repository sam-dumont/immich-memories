"""The chain a free-text request's exclusions travel: `--ask`'s `CuratedPool`, the album
preset params `_album_generation.py` builds from it, the run context `_editorial_context.py`
derives, and the editorial brief `build_editorial_intent` renders (#2061 round 3)."""

from __future__ import annotations

from datetime import datetime

from immich_memories.analysis.editorial_intent import build_editorial_intent
from immich_memories.cli._album_generation import CuratedPool
from immich_memories.cli._editorial_context import build_editorial_context
from immich_memories.cli._run_inputs import ResolvedRunInputs
from immich_memories.config_loader import Config
from immich_memories.free_text.handoff import Film
from immich_memories.free_text.linking import Reason
from immich_memories.timeperiod import DateRange

SUBJECT = "landscapes, no humans"


def _preset_params(curated: CuratedPool, subject: str | None) -> dict:
    """The same expression `_album_generation.handle_album_generation` builds."""
    return (
        {"album_name": curated.name, "album_id": curated.ref}
        | ({"subject": subject} if subject else {})
        | ({"excluded_phrases": list(curated.excluded)} if curated.excluded else {})
        | (
            {"excluded_person_ids": list(curated.excluded_person_ids)}
            if curated.excluded_person_ids
            else {}
        )
    )


def test_exclusions_travel_from_ask_to_the_editorial_brief():
    # 1. `--ask`'s `scope_of_ask` builds the film, then the curated pool from it.
    film = Film(
        route="pool",
        reason=Reason("", "", ""),
        asset_ids=("a1", "a2"),
        subject=SUBJECT,
        window=DateRange(datetime(2024, 3, 10), datetime(2024, 5, 20, 23, 59, 59)),
        excluded=("people",),
        excluded_person_ids=("cy",),
    )
    curated = CuratedPool(
        name=SUBJECT,
        ref="ask-abc123",
        asset_ids=film.asset_ids,
        window=film.window,
        excluded=film.excluded,
        excluded_person_ids=film.excluded_person_ids,
    )

    # 2. `handle_album_generation` folds the curated pool into the preset params.
    preset_params = _preset_params(curated, subject=SUBJECT)
    assert preset_params["excluded_phrases"] == ["people"]
    assert preset_params["excluded_person_ids"] == ["cy"]

    # 3. `build_editorial_context` reads them into the run context, for a subject pool only.
    config = Config()
    resolved = ResolvedRunInputs.from_arguments(
        include_photos=False,
        photo_assets=None,
        dry_run=False,
        automation_attempt_id=None,
        upload_to_immich=False,
        config=config,
        person_names=[],
        music=None,
        memory_preset_params=preset_params,
    )
    context = build_editorial_context(
        resolved=resolved,
        config=config,
        memory_type="album",
        memory_key=None,
        output_stem="ask",
        assets=[object()],
        date_range=film.window,
        date_ranges=(),
        duration=60.0,
        transition="smart",
        title_override=None,
        person_names=[],
        accept_any_provenance=True,
    )
    assert context.pool_subject == SUBJECT
    assert context.excluded == ("people",)
    assert context.excluded_person_ids == ("cy",)

    # 4. The editorial brief carries them as its own hard rule.
    intent = build_editorial_intent(
        "album",
        (film.window,),
        brief=context.pool_subject,
        pool_subject=context.pool_subject,
        excluded=context.excluded,
    )
    assert intent.excluded == ("people",)
    assert "must not show: people" in intent.prompt_block()
