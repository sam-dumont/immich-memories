"""`generate --ask`: a film asked for in a sentence, translated before anything runs.

Every picture, caption and word here is invented; the model's answers come from the bank.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from immich_memories.api.models import Asset, MetadataSearchResult
from immich_memories.config_models_editorial import EditorialConfig
from immich_memories.db import open_store
from immich_memories.free_text.lexicon import WordNetLexicon
from tests.annotation_rows import add_rows
from tests.free_text.banked import QuestionAsker

EDITORIAL = EditorialConfig()
IMMICH = "immich:\n  url: http://immich.invalid\n  api_key: not-a-real-key\n"
MODEL_TIER = "tier: full\nadvanced:\n  llm:\n    base_url: http://reader.invalid/v1\n    model: small-reader\n"
ANSWERS: dict[str, Any] = {
    "Split the owner's request": {
        "who": [],
        "when": ["along the years"],
        "where": [],
        "what": ["our cat"],
    },
    "Give the date range": {"date_from": None, "date_to": None},
    "would be written on something": {"reason": "banked", "choices": []},
    "one single occasion": {"reason": "banked", "choice": "many occasions"},
    "name the main subject itself too": {"reason": "banked", "choices": []},
}


FIRST = datetime(2019, 1, 1, 12, tzinfo=UTC)
SHOTS = [(f"cat-{n}", FIRST + timedelta(days=40 * n), "A black cat is sleeping") for n in range(14)]
SHOTS += [(f"dog-{n}", FIRST + timedelta(days=n), "A dog on a beach") for n in range(5)]


def _library() -> None:
    store = open_store()
    add_rows(
        store,
        "annotation_assets",
        *({"asset_id": i, "taken_at": at.isoformat(), "media_kind": "photo"} for i, at, _ in SHOTS),
    )
    add_rows(
        store,
        "descriptions",
        *({"asset_id": i, "model": EDITORIAL.description_model, "text": c} for i, _, c in SHOTS),
    )


def _asset(asset_id: str, at: datetime) -> Asset:
    return Asset(
        id=asset_id,
        type="IMAGE",
        file_created_at=at,
        file_modified_at=at,
        updated_at=at,
        original_file_name=f"IMG_{asset_id}.JPG",
        width=4032,
        height=3024,
    )


class _InventedImmich:
    """WHY: replaces the Immich HTTP API; it answers for the invented library and counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    def search_metadata(self, *, page, size, taken_after, taken_before, **_filters):
        self.calls += 1
        inside = [
            _asset(shot, taken) for shot, taken, _ in SHOTS if taken_after <= taken <= taken_before
        ]
        items = inside[(page - 1) * size : page * size]
        more = page * size < len(inside)
        return MetadataSearchResult.model_validate(
            {"assets": {"items": items, "total": len(items), "nextPage": "2" if more else None}}
        )

    def get_asset(self, asset_id: str) -> Asset:
        raise AssertionError(f"one read per picture ({asset_id}): read the pool in pages")

    def __enter__(self) -> _InventedImmich:
        return self

    def __exit__(self, *_exc) -> bool:
        return False


@pytest.fixture
def ask(tmp_path: Path, lexicon: WordNetLexicon, monkeypatch: pytest.MonkeyPatch):
    """Run `generate --ask` through argv against an invented library."""
    from immich_memories.cli import main

    _library()
    # The config directory is made under the home directory: a throwaway one here.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # WHY: the pinned WordNet corpus is a model download; this one holds the test's words.
    monkeypatch.setattr("immich_memories.cli._ask_generation.load_wordnet", lambda _path: lexicon)
    immich = _InventedImmich()
    monkeypatch.setattr("immich_memories.api.immich.SyncImmichClient", lambda **_k: immich)

    def _invoke(
        *args: str, config: str = IMMICH + MODEL_TIER, answers: dict[str, Any] = ANSWERS
    ) -> Result:
        # WHY: the model server; its answers come from the one bank of model answers.
        monkeypatch.setattr(
            "immich_memories.cli._ask_generation.WireAsker",
            lambda *_a, **_k: QuestionAsker(answers),
        )
        path = tmp_path / "config.yaml"
        path.write_text(config)
        return CliRunner().invoke(main, ["-c", str(path), "generate", *args])

    _invoke.immich = immich  # type: ignore[attr-defined]
    yield _invoke


def test_a_dry_run_prints_the_translation_and_the_pool_and_films_nothing(ask) -> None:
    result = ask("--ask", "our cat along the years", "--dry-run")

    assert result.exit_code == 0, result.output
    assert '"our cat along the years"' in result.output
    assert "READING" in result.output and "VERDICT  possible" in result.output
    assert "14 pictures (14 photos, 0 videos)" in result.output


def test_a_dry_run_keeps_its_translation_for_a_watcher(ask, tmp_path: Path) -> None:
    import json

    kept = tmp_path / "ask.json"

    result = ask("--ask", "our cat along the years", "--dry-run", "--ask-trace", str(kept))

    assert result.exit_code == 0, result.output
    record = json.loads(kept.read_text())
    assert record["request"] == "our cat along the years"
    assert [block["head"] for block in record["blocks"]][:2] == ["READING", "WHO"]
    assert record["pool"] == {"pictures": 14, "photos": 14, "videos": 0}
    assert record["verdict"] == "possible"
    assert record["film"]["route"] == "pool"


def test_the_run_report_carries_the_translation_the_watcher_reads(
    ask, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from immich_memories.cli import main

    # WHY: the album run reads Immich and renders; the run's kept translation is under test.
    monkeypatch.setattr(
        "immich_memories.cli._album_generation.handle_album_generation", lambda **_k: None
    )
    ask("--ask", "our cat along the years", "--no-render")

    reported = CliRunner().invoke(main, ["-c", str(tmp_path / "config.yaml"), "report", "--json"])

    assert reported.exit_code == 0, reported.output
    translation = json.loads(reported.stdout)["free_text"]["translation"]
    assert translation["pool"] == {"pictures": 14, "photos": 14, "videos": 0}
    assert translation["film"]["route"] == "pool"


def test_a_film_runs_report_carries_the_rules_its_pool_met(
    ask, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from immich_memories.cli import main

    add_rows(
        open_store(),
        "asset_flags",
        {"asset_id": "cat-3", "flag": "never_auto", "source": "nsfw_marqo"},
    )
    # WHY: the album run reads Immich and renders; the run's kept rule preview is under test.
    monkeypatch.setattr(
        "immich_memories.cli._album_generation.handle_album_generation", lambda **_k: None
    )
    ask("--ask", "our cat along the years", "--no-render")

    reported = CliRunner().invoke(main, ["-c", str(tmp_path / "config.yaml"), "report", "--json"])

    assert reported.exit_code == 0, reported.output
    rules = json.loads(reported.stdout)["free_text"]["translation"]["rules"]
    assert (rules["checked"], rules["passed"]) == (14, 13)
    assert "cat-3" not in reported.stdout


def test_a_dry_run_shows_which_rules_would_drop_pool_pictures(ask, tmp_path: Path) -> None:
    import json

    add_rows(
        open_store(),
        "asset_flags",
        {"asset_id": "cat-3", "flag": "never_auto", "source": "nsfw_marqo"},
    )
    kept = tmp_path / "ask.json"

    result = ask("--ask", "our cat along the years", "--dry-run", "--ask-trace", str(kept))

    assert result.exit_code == 0, result.output
    assert "RULES    13 of 14 pictures pass the rules checked before cutting" in result.output
    held = next(line for line in result.output.splitlines() if "held for review: 1" in line)
    assert " id-" in held and "cat-3" not in result.output.split("RULES", 1)[1]
    assert "decided while cutting: who sees it" in result.output
    # The 14-picture pool is one page of Immich's search, not 14 single reads.
    assert ask.immich.calls == 1
    rules = json.loads(kept.read_text())["rules"]
    assert (rules["checked"], rules["passed"]) == (14, 13)
    assert [(d["rule"], d["count"], d["examples"]) for d in rules["drops"]] == [
        ("held for review", 1, ["cat-3"])
    ]


def test_without_the_model_tier_the_ask_says_what_it_needs(ask) -> None:
    result = ask("--ask", "our cat along the years", "--dry-run", config=IMMICH)

    assert result.exit_code == 2
    assert "--ask needs the model tier" in result.output


def test_a_flag_the_sentence_already_says_is_refused(ask) -> None:
    result = ask("--ask", "our cat along the years", "--year", "2020", "--dry-run")

    assert result.exit_code == 2
    assert "--ask is the whole scope; drop --year" in result.output


def test_the_pool_is_handed_to_the_engine_as_an_album_of_its_subject(
    ask, monkeypatch: pytest.MonkeyPatch
) -> None:
    handed: dict[str, Any] = {}
    # WHY: the album run reads Immich and renders; what it is handed is under test.
    monkeypatch.setattr(
        "immich_memories.cli._album_generation.handle_album_generation",
        lambda **kwargs: handed.update(kwargs),
    )

    result = ask("--ask", "our cat along the years", "--no-render", "--duration", "40")

    assert result.exit_code == 0, result.output
    pool = handed["curated"]
    assert set(pool.asset_ids) == {f"cat-{n}" for n in range(14)}
    assert handed["subject"] == "our cat along the years"
    assert handed["album_ref"] == pool.ref
    assert handed["accept_any_provenance"] is True
    assert handed["duration"] == 40


def test_a_request_the_library_cannot_show_makes_no_film_and_says_why(ask) -> None:
    horse = {
        **ANSWERS,
        "Split the owner's request": {
            **ANSWERS["Split the owner's request"],
            "what": ["our horse"],
        },
    }

    result = ask("--ask", "our horse along the years", answers=horse)

    assert result.exit_code == 0, result.output
    assert "VERDICT  not possible: nothing left after subject" in result.output
    assert "Not possible, no film" in result.output


class _RecordingImmich:
    """WHY: replaces the Immich HTTP API, keeping the windows the run asked for."""

    def __init__(self) -> None:
        self.windows: list = []

    def get_videos_for_date_range(self, date_range) -> list:
        self.windows.append(date_range)
        return []

    def __enter__(self) -> _RecordingImmich:
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def test_one_undated_occasion_is_filmed_as_its_special_day(
    ask, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_rows(
        open_store(),
        "annotation_assets",
        {"asset_id": "w-1", "taken_at": "2017-05-20T15:00:00+00:00", "media_kind": "photo"},
    )
    add_rows(
        open_store(),
        "descriptions",
        {"asset_id": "w-1", "model": EDITORIAL.description_model, "text": "A wedding cake"},
    )
    immich = _RecordingImmich()
    monkeypatch.setattr("immich_memories.api.immich.SyncImmichClient", lambda **_k: immich)
    wedding = {
        **ANSWERS,
        "Split the owner's request": {"who": [], "when": [], "where": [], "what": ["our wedding"]},
        "one single occasion": {"reason": "banked", "choice": "one single occasion"},
    }

    ask("--ask", "our wedding", "--no-photos", "--no-live-photos", answers=wedding)

    assert [window.start.date() for window in immich.windows] == [date(2017, 5, 20)]
