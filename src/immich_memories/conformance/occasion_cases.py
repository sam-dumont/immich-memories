"""Synthetic occasions compared with ordinary days and calendar holidays."""

from datetime import timedelta
from functools import partial
from types import SimpleNamespace

from immich_memories.analysis.special_day import ask_if_special
from immich_memories.analysis.special_day_holiday import was_the_holiday
from immich_memories.analysis.special_day_sequence import read_in_sequence
from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.fixtures import race_assets, scratch_store
from immich_memories.conformance.runtime import Case


def holiday(llm: LLMConfig) -> str:
    answer = was_the_holiday(
        "Christmas", "Cycling race", "Cyclists crossing a finish line in a race", llm, None
    )
    assert answer is False, "race was mistaken for the calendar holiday"
    return "cycling race is distinct from Christmas"


def occasion(llm: LLMConfig, *, captioned: bool) -> str:
    assets = race_assets()
    captions = {asset.id: asset.llm_description for asset in assets} if captioned else None
    with scratch_store() as (_, store):
        answer = ask_if_special(assets, llm, captions=captions, judgments=store)
    assert answer.judged and answer.special, "race was not recognized as an occasion"
    assert any(
        word in (answer.title + " " + answer.what).lower()
        for word in ("race", "cycling", "cyclist")
    ), "occasion lost the cycling evidence"
    return "recognizes and names the cycling race"


def sequence(llm: LLMConfig) -> str:
    race = race_assets()
    quiet = [
        SimpleNamespace(
            **(
                vars(asset)
                | {
                    "id": asset.id.replace("race", "quiet"),
                    "file_created_at": asset.file_created_at + timedelta(days=7),
                    "llm_description": "A cat sleeping on the sofa at home on an ordinary afternoon",
                }
            )
        )
        for asset in race
    ]
    race_day, quiet_day = race[0].file_created_at.date(), quiet[0].file_created_at.date()
    with scratch_store() as (_, store):
        answer = read_in_sequence(
            {race_day: race, quiet_day: quiet},
            captions={asset.id: asset.llm_description for asset in race + quiet},
            llm_config=llm,
            judgments=store,
        )
    assert set(answer.found) == {race_day}, "sequence did not distinguish race from ordinary day"
    return "finds the race and leaves the ordinary afternoon out"


def occasion_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case(
            "occasion sequence",
            partial(sequence, llm),
            frozenset({"analysis.special_day_sequence:_read"}),
        ),
        Case(
            "captioned occasion",
            partial(occasion, llm, captioned=True),
            frozenset(
                {
                    "analysis.special_day:_ask_from_captions",
                    "analysis.editorial_text_gateway:QueryTextRequester._transported",
                }
            ),
        ),
        Case(
            "recorded occasion",
            partial(occasion, llm, captioned=False),
            frozenset({"analysis.special_day:_ask"}),
        ),
        Case(
            "holiday distinction",
            partial(holiday, llm),
            frozenset({"analysis.special_day_holiday:_ask"}),
        ),
    )
