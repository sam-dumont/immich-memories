"""`generate --ask`: a film asked for in a sentence, translated before anything runs.

Every picture, caption and word here is invented; the model's answers come from the bank.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from immich_memories.analysis.editorial_preparation import PreparationResult
from immich_memories.api.models import Asset, MetadataSearchResult
from immich_memories.api.permissions import READ_PERMISSIONS, ApiKeyCapabilities
from immich_memories.config_models_editorial import EditorialConfig
from immich_memories.db import open_store
from immich_memories.free_text.lexicon import WordNetLexicon
from tests.annotation_rows import add_rows
from tests.free_text.banked import QuestionAsker

EDITORIAL = EditorialConfig()
IMMICH = "immich:\n  url: http://immich.invalid\n  api_key: not-a-real-key\n"
MODEL_TIER = "tier: full\nadvanced:\n  llm:\n    enabled: true\n    base_url: http://reader.invalid/v1\n    model: small-reader\n"
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


class _ReadableKey:
    """The invented API key grants exactly the film's required read permissions."""

    def get_key_capabilities(self) -> ApiKeyCapabilities:
        return ApiKeyCapabilities(frozenset(READ_PERMISSIONS))

    def require_read_permissions(self) -> None:
        self.get_key_capabilities().require_read()


def _camera_asset(asset_id: str, at: datetime) -> Asset:
    """A picture Immich would admit into preparation: EXIF names a camera."""
    from immich_memories.api.models import ExifInfo

    return _asset(asset_id, at).model_copy(
        update={"exif_info": ExifInfo(make="Apple", model="iPhone 15 Pro")}
    )


class _InventedImmich(_ReadableKey):
    """WHY: replaces the Immich HTTP API; it answers for the invented library and counts calls."""

    def __init__(self) -> None:
        self.calls = 0
        # Pictures Immich holds that the store has never synced: discovered only by
        # the window-check's own fetch, never by a cheaper read of what is banked.
        self.unsynced_camera_shots: list[tuple[str, datetime]] = []

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

    # `--ask` checks the request's window is prepared before it reads it (#2045). None of
    # the invented library's own pictures carries camera EXIF, so the admission pass drops
    # every one of them and preparation never has anything to warn about or to prepare.
    def get_available_years(self, person_id: str | None = None) -> list[int]:
        years = {taken.year for _, taken, _ in SHOTS} | {
            at.year for _, at in self.unsynced_camera_shots
        }
        return sorted(years)

    def get_videos_for_date_range(self, date_range) -> list:
        return []

    def get_photos_for_date_range(self, date_range) -> list:
        start, end = date_range.start.replace(tzinfo=UTC), date_range.end.replace(tzinfo=UTC)
        return [_asset(shot, taken) for shot, taken, _ in SHOTS if start <= taken <= end] + [
            _camera_asset(shot, taken)
            for shot, taken in self.unsynced_camera_shots
            if start <= taken <= end
        ]

    def get_live_photos_for_date_range(self, date_range) -> list:
        return []

    # Bound but never called: the caption producer itself is mocked out in these tests.
    def get_asset_thumbnail(self, asset_id: str, size: str = "preview") -> bytes:
        raise AssertionError("the caption producer is mocked; it should never read a thumbnail")

    def get_asset_faces(self, asset_id: str) -> list:
        raise AssertionError("the caption producer is mocked; it should never read a face")

    def get_video_playback_range(self, asset_id: str, start: int, length: int):
        raise AssertionError("the caption producer is mocked; it should never read playback")

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


class _RecordingImmich(_ReadableKey):
    """WHY: replaces the Immich HTTP API, keeping the windows the run asked for."""

    def __init__(self) -> None:
        self.windows: list = []

    def get_videos_for_date_range(self, date_range) -> list:
        self.windows.append(date_range)
        return []

    # `--ask` checks the request's window is prepared first (#2045); this invented library
    # has no years and no photos of its own, so that check finds nothing missing.
    def get_available_years(self, person_id: str | None = None) -> list[int]:
        return []

    def get_photos_for_date_range(self, date_range) -> list:
        return []

    def get_live_photos_for_date_range(self, date_range) -> list:
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

    # The window-check that runs first (#2045) also asks for videos, over the whole
    # library; the occasion's own, narrower window is what the film is actually cut from.
    assert date(2017, 5, 20) in [window.start.date() for window in immich.windows]


def _captioning(store, text: str):
    """WHY: replaces the configured caption model; writes exactly what it was asked for."""

    def _prepare(**kwargs) -> PreparationResult:
        from immich_memories.tracking.timing import span

        assets = kwargs["assets"]
        total = len(assets)
        with span("preparation.captions", items=total):
            add_rows(
                store,
                "annotation_assets",
                *(
                    {
                        "asset_id": asset.id,
                        "taken_at": asset.file_created_at.isoformat(),
                        "media_kind": "photo",
                    }
                    for asset in assets
                ),
            )
            add_rows(
                store,
                "descriptions",
                *(
                    {"asset_id": asset.id, "model": EDITORIAL.description_model, "text": text}
                    for asset in assets
                ),
            )
            kwargs["progress"]("captions", total, total)
        return PreparationResult(requested=total, missing_by_producer={}, failures={})

    return _prepare


def test_an_unprepared_window_is_warned_about_prepared_and_then_answered(
    ask, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2045: the owner's ruling -- warn with the count and an estimate, prepare, then answer."""
    from immich_memories.cli import main

    store = open_store()
    # Three cat pictures Immich holds that the store has never synced, let alone captioned.
    ask.immich.unsynced_camera_shots = [
        (f"new-cat-{n}", FIRST + timedelta(days=1000 + n)) for n in range(3)
    ]
    monkeypatch.setattr(
        "immich_memories.analysis.editorial_preparation.prepare_editorial_annotations",
        _captioning(store, "A black cat is sleeping"),
    )
    monkeypatch.setattr(
        "immich_memories.cli._album_generation.handle_album_generation", lambda **_k: None
    )

    result = ask("--ask", "our cat along the years", "--no-render")

    assert result.exit_code == 0, result.output
    assert (
        "3 pictures in this period aren't prepared yet; preparing them first takes about"
        in result.output
    )
    assert "Preparing 3 pictures over 1 window" in result.output
    reported = CliRunner().invoke(main, ["-c", str(tmp_path / "config.yaml"), "report", "--json"])
    translation = json.loads(reported.stdout)["free_text"]["translation"]
    # The newly captioned pictures read as the same subject, so the pool grew to hold them.
    assert translation["pool"]["pictures"] == 17


def test_a_fully_prepared_window_is_neither_warned_about_nor_prepared(ask) -> None:
    """#2045: every picture already carries a caption, so the window needs nothing done."""
    result = ask("--ask", "our cat along the years", "--dry-run")

    assert result.exit_code == 0, result.output
    assert "aren't prepared yet" not in result.output
    assert "Preparing " not in result.output


def test_preflight_runs_before_preparation_but_not_on_a_dry_run_or_a_prepared_window(
    ask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2045 (Opus review H): the model-install preflight `prepare` itself runs, before
    any producer touches a picture -- never on a preview, never when nothing is missing."""
    calls: list[str] = []
    monkeypatch.setattr(
        "immich_memories.cli._ask_generation.refuse_blocked_host",
        lambda *_a, **_k: calls.append("preflight"),
    )

    ask("--ask", "our cat along the years", "--dry-run")
    assert calls == []

    ask.immich.unsynced_camera_shots = [("new-cat-0", FIRST + timedelta(days=1000))]
    monkeypatch.setattr(
        "immich_memories.analysis.editorial_preparation.prepare_editorial_annotations",
        _captioning(open_store(), "A black cat is sleeping"),
    )
    monkeypatch.setattr(
        "immich_memories.cli._album_generation.handle_album_generation", lambda **_k: None
    )

    ask("--ask", "our cat along the years", "--no-render")
    assert calls == ["preflight"]


def test_a_dry_run_on_an_unprepared_window_only_warns_and_prepares_nothing(
    ask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2045 owner ruling: a dry run previews the cost of preparing; it never pays it."""
    ask.immich.unsynced_camera_shots = [("new-cat-0", FIRST + timedelta(days=1000))]

    def _never(**_kwargs):
        raise AssertionError("a dry run must never call the real preparation pipeline")

    monkeypatch.setattr(
        "immich_memories.analysis.editorial_preparation.prepare_editorial_annotations", _never
    )

    result = ask("--ask", "our cat along the years", "--dry-run")

    assert result.exit_code == 0, result.output
    assert "1 pictures in this period aren't prepared yet; preparing them first takes about" in (
        result.output
    )
    assert "Preparing 1 pictures over 1 window" not in result.output


def test_a_preparation_failure_is_reported_and_never_reads_as_not_possible(
    ask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2045 (Opus review A): a producer failure is named, not swallowed into "not possible"."""
    ask.immich.unsynced_camera_shots = [("new-cat-0", FIRST + timedelta(days=1000))]

    def _broken(**kwargs):
        from immich_memories.analysis.editorial_preparation import PreparationResult

        total = len(kwargs["assets"])
        kwargs["progress"]("captions", total, total)
        return PreparationResult(
            requested=total, missing_by_producer={}, failures={"cat-new-cat-0": "reader down"}
        )

    monkeypatch.setattr(
        "immich_memories.analysis.editorial_preparation.prepare_editorial_annotations", _broken
    )

    result = ask("--ask", "our cat along the years", "--no-render")

    assert result.exit_code == 1, result.output
    assert "could not be prepared" in result.output
    assert "reader down" in result.output
    assert "not possible" not in result.output.lower()


def test_an_impossible_request_on_a_prepared_library_still_says_not_possible(ask) -> None:
    """#2045: "not possible" survives for a subject that is genuinely nowhere in the library."""
    horse = {
        **ANSWERS,
        "Split the owner's request": {
            **ANSWERS["Split the owner's request"],
            "what": ["our horse"],
        },
    }

    result = ask("--ask", "our horse along the years", answers=horse)

    assert result.exit_code == 0, result.output
    assert "aren't prepared yet" not in result.output
    assert "VERDICT  not possible: nothing left after subject" in result.output
    assert "Not possible, no film" in result.output
