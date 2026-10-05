"""`generate --ask`: a film asked for in a sentence, translated before anything runs.

Every picture, caption and word here is invented; the model's answers come from the bank.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
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
from immich_memories.preflight import CheckResult, CheckStatus
from immich_memories.store.editorial_preparation import remember_assets
from tests.annotation_rows import add_rows
from tests.free_text.banked import QuestionAsker

EDITORIAL = EditorialConfig()
# A healthy preflight read for the caption service: every `ask` fixture test stubs the
# real HTTP reachability check with this, so none of them depend on a server being up.
_OK_CAPTIONS = CheckResult("Captions", CheckStatus.OK, "ok")
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
    # These rows stand in for a real `prepare`, which is the only path that ever confirms
    # this (#2044); without it a fresh store defaults to the safe, account-scoped read and
    # every test below would need a household-capable fake client just to run `--ask`.
    remember_assets(store, [])


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
    # WHY: replaces the Immich HTTP API with the invented library above.
    monkeypatch.setattr("immich_memories.api.immich.SyncImmichClient", lambda **_k: immich)
    # WHY: replaces reaching the real caption server over HTTP to check it is up.
    monkeypatch.setattr(
        "immich_memories.preflight.check_caption_endpoint",
        lambda _config: _OK_CAPTIONS,
    )

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


def test_ask_never_counts_or_traces_another_accounts_pictures(
    tmp_path: Path, lexicon: WordNetLexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two accounts share one store (#2044): the store holds captions for both, but a
    request naming only one account never counts, traces or previews the other's picture,
    even though both are about the same subject."""
    import json

    import yaml

    from immich_memories.cli import main
    from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

    store = open_store()
    add_rows(
        store,
        "annotation_assets",
        {"asset_id": "p-cat", "taken_at": "2020-01-01T12:00:00+00:00", "media_kind": "photo"},
        {"asset_id": "q-cat", "taken_at": "2020-01-02T12:00:00+00:00", "media_kind": "photo"},
    )
    add_rows(
        store,
        "descriptions",
        {
            "asset_id": "p-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
        {
            "asset_id": "q-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
    )
    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-cat", "primary", 1, ())],
            PARTNER_KEY: [picture("q-cat", "partner", 2, ())],
        }
    ).install(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # WHY: the pinned WordNet corpus is a model download; this one holds the test's words.
    monkeypatch.setattr("immich_memories.cli._ask_generation.load_wordnet", lambda _path: lexicon)
    # WHY: the model server; its answers come from the one bank of model answers.
    monkeypatch.setattr(
        "immich_memories.cli._ask_generation.WireAsker", lambda *_a, **_k: QuestionAsker(ANSWERS)
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "immich": immich_config(),
                "tier": "full",
                "advanced": {
                    "llm": {
                        "enabled": True,
                        "base_url": "http://reader.invalid/v1",
                        "model": "small-reader",
                    }
                },
            }
        )
    )
    trace_file = tmp_path / "ask.json"

    result = CliRunner().invoke(
        main,
        [
            "-c",
            str(config_path),
            "generate",
            "--ask",
            "our cat along the years",
            "--accounts",
            "partner",
            "--dry-run",
            "--ask-trace",
            str(trace_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "p-cat" not in result.output
    record = json.loads(trace_file.read_text())
    assert record["pool"] == {"pictures": 1, "photos": 1, "videos": 0}
    assert "p-cat" not in json.dumps(record)


def test_a_plain_ask_defaults_to_the_primary_when_the_config_has_a_household(
    tmp_path: Path, lexicon: WordNetLexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A household that once ran `--accounts` left the partner's pictures in the one,
    ownerless store (#2044): naming no account at all must not fall back to reading all of
    it, just because `run_accounts` turns "no --accounts" into the one-account run's empty
    tuple. Configuring a partner account is enough to default this request to the primary
    account alone, exactly as a dated run already reads without `--accounts`."""
    import json

    import yaml

    from immich_memories.cli import main
    from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

    store = open_store()
    add_rows(
        store,
        "annotation_assets",
        {"asset_id": "p-cat", "taken_at": "2020-01-01T12:00:00+00:00", "media_kind": "photo"},
        {"asset_id": "q-cat", "taken_at": "2020-01-02T12:00:00+00:00", "media_kind": "photo"},
    )
    add_rows(
        store,
        "descriptions",
        {
            "asset_id": "p-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
        {
            "asset_id": "q-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
    )
    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-cat", "primary", 1, ())],
            PARTNER_KEY: [picture("q-cat", "partner", 2, ())],
        }
    ).install(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # WHY: the pinned WordNet corpus is a model download; this one holds the test's words.
    monkeypatch.setattr("immich_memories.cli._ask_generation.load_wordnet", lambda _path: lexicon)
    # WHY: the model server; its answers come from the one bank of model answers.
    monkeypatch.setattr(
        "immich_memories.cli._ask_generation.WireAsker", lambda *_a, **_k: QuestionAsker(ANSWERS)
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "immich": immich_config(),
                "tier": "full",
                "advanced": {
                    "llm": {
                        "enabled": True,
                        "base_url": "http://reader.invalid/v1",
                        "model": "small-reader",
                    }
                },
            }
        )
    )
    trace_file = tmp_path / "ask.json"

    # No --accounts at all: the household is only in the config, not on the command line.
    result = CliRunner().invoke(
        main,
        [
            "-c",
            str(config_path),
            "generate",
            "--ask",
            "our cat along the years",
            "--dry-run",
            "--ask-trace",
            str(trace_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "q-cat" not in result.output
    record = json.loads(trace_file.read_text())
    assert record["pool"] == {"pictures": 1, "photos": 1, "videos": 0}
    assert "q-cat" not in json.dumps(record)


def test_a_plain_ask_still_scopes_to_the_primary_after_the_household_leaves_config(
    tmp_path: Path, lexicon: WordNetLexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A household run once wrote the partner's picture into this store through
    `remember_assets` (the real preparation path), which stamps a sticky `household_seen`
    marker (#2044). Removing the partner from config and turning off native sharing must
    not un-poison the store: a plain `--ask` naming no account still has to read as the
    primary alone, the same as when the household is still configured."""
    import json

    import yaml

    from immich_memories.cli import main
    from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

    store = open_store()
    add_rows(
        store,
        "annotation_assets",
        {"asset_id": "p-cat", "taken_at": "2020-01-01T12:00:00+00:00", "media_kind": "photo"},
        {"asset_id": "q-cat", "taken_at": "2020-01-02T12:00:00+00:00", "media_kind": "photo"},
    )
    add_rows(
        store,
        "descriptions",
        {
            "asset_id": "p-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
        {
            "asset_id": "q-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
    )
    # The household's own earlier preparation run, stamping the sticky marker.
    remember_assets(
        store,
        [
            _asset("q-cat", datetime(2020, 1, 2, 12, tzinfo=UTC)).model_copy(
                update={"access_accounts": ("partner",)}
            )
        ],
    )
    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-cat", "primary", 1, ())],
            PARTNER_KEY: [picture("q-cat", "partner", 2, ())],
        }
    ).install(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # WHY: the pinned WordNet corpus is a model download; this one holds the test's words.
    monkeypatch.setattr("immich_memories.cli._ask_generation.load_wordnet", lambda _path: lexicon)
    # WHY: the model server; its answers come from the one bank of model answers.
    monkeypatch.setattr(
        "immich_memories.cli._ask_generation.WireAsker", lambda *_a, **_k: QuestionAsker(ANSWERS)
    )
    config_path = tmp_path / "config.yaml"
    household = immich_config()
    # The partner has since been removed, and native sharing was never turned on either:
    # the config alone now looks like a plain, single-account install.
    config_path.write_text(
        yaml.safe_dump(
            {
                "immich": {
                    "url": household["url"],
                    "api_key": household["api_key"],
                    "api_version": household["api_version"],
                },
                "tier": "full",
                "advanced": {
                    "llm": {
                        "enabled": True,
                        "base_url": "http://reader.invalid/v1",
                        "model": "small-reader",
                    }
                },
            }
        )
    )
    trace_file = tmp_path / "ask.json"

    result = CliRunner().invoke(
        main,
        [
            "-c",
            str(config_path),
            "generate",
            "--ask",
            "our cat along the years",
            "--dry-run",
            "--ask-trace",
            str(trace_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "q-cat" not in result.output
    record = json.loads(trace_file.read_text())
    assert record["pool"] == {"pictures": 1, "photos": 1, "videos": 0}
    assert "q-cat" not in json.dumps(record)


def test_a_single_account_install_keeps_its_whole_pool_under_the_safe_default(
    tmp_path: Path, lexicon: WordNetLexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuinely single-account install, with no config household, no native sharing and
    no `store_meta` marker yet, still gets the safe, scoped-to-primary read (#2044) -- but
    every one of its own pictures is the primary's, so the scoped read must come back with
    the whole pool, not a narrower one."""
    import json

    import yaml

    from immich_memories.cli import main
    from tests.household_fake import PRIMARY_KEY, FakeHousehold, picture

    store = open_store()
    add_rows(
        store,
        "annotation_assets",
        {"asset_id": "p-cat", "taken_at": "2020-01-01T12:00:00+00:00", "media_kind": "photo"},
        {"asset_id": "p-dog", "taken_at": "2020-01-02T12:00:00+00:00", "media_kind": "photo"},
    )
    add_rows(
        store,
        "descriptions",
        {
            "asset_id": "p-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
        {
            "asset_id": "p-dog",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
    )
    FakeHousehold(
        library={
            PRIMARY_KEY: [
                picture("p-cat", "primary", 1, ()),
                picture("p-dog", "primary", 2, ()),
            ]
        }
    ).install(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # WHY: the pinned WordNet corpus is a model download; this one holds the test's words.
    monkeypatch.setattr("immich_memories.cli._ask_generation.load_wordnet", lambda _path: lexicon)
    # WHY: the model server; its answers come from the one bank of model answers.
    monkeypatch.setattr(
        "immich_memories.cli._ask_generation.WireAsker", lambda *_a, **_k: QuestionAsker(ANSWERS)
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "immich": {
                    "url": "https://immich.example.test",
                    "api_key": PRIMARY_KEY,
                    "api_version": "v2",
                },
                "tier": "full",
                "advanced": {
                    "llm": {
                        "enabled": True,
                        "base_url": "http://reader.invalid/v1",
                        "model": "small-reader",
                    }
                },
            }
        )
    )
    trace_file = tmp_path / "ask.json"

    result = CliRunner().invoke(
        main,
        [
            "-c",
            str(config_path),
            "generate",
            "--ask",
            "our cat along the years",
            "--dry-run",
            "--ask-trace",
            str(trace_file),
        ],
    )

    assert result.exit_code == 0, result.output
    record = json.loads(trace_file.read_text())
    assert record["pool"] == {"pictures": 2, "photos": 2, "videos": 0}


def test_ask_counts_every_named_accounts_pictures(
    tmp_path: Path, lexicon: WordNetLexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming every account a household has keeps the whole, correctly-owned pool: this is
    not a one-account cut, it is the pool every account named is allowed to see."""
    import json

    import yaml

    from immich_memories.cli import main
    from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

    store = open_store()
    add_rows(
        store,
        "annotation_assets",
        {"asset_id": "p-cat", "taken_at": "2020-01-01T12:00:00+00:00", "media_kind": "photo"},
        {"asset_id": "q-cat", "taken_at": "2020-01-02T12:00:00+00:00", "media_kind": "photo"},
    )
    add_rows(
        store,
        "descriptions",
        {
            "asset_id": "p-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
        {
            "asset_id": "q-cat",
            "model": EDITORIAL.description_model,
            "text": "A black cat is sleeping",
        },
    )
    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-cat", "primary", 1, ())],
            PARTNER_KEY: [picture("q-cat", "partner", 2, ())],
        }
    ).install(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # WHY: the pinned WordNet corpus is a model download; this one holds the test's words.
    monkeypatch.setattr("immich_memories.cli._ask_generation.load_wordnet", lambda _path: lexicon)
    # WHY: the model server; its answers come from the one bank of model answers.
    monkeypatch.setattr(
        "immich_memories.cli._ask_generation.WireAsker", lambda *_a, **_k: QuestionAsker(ANSWERS)
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "immich": immich_config(),
                "tier": "full",
                "advanced": {
                    "llm": {
                        "enabled": True,
                        "base_url": "http://reader.invalid/v1",
                        "model": "small-reader",
                    }
                },
            }
        )
    )
    trace_file = tmp_path / "ask.json"

    result = CliRunner().invoke(
        main,
        [
            "-c",
            str(config_path),
            "generate",
            "--ask",
            "our cat along the years",
            "--accounts",
            "primary,partner",
            "--dry-run",
            "--ask-trace",
            str(trace_file),
        ],
    )

    assert result.exit_code == 0, result.output
    record = json.loads(trace_file.read_text())
    assert record["pool"] == {"pictures": 2, "photos": 2, "videos": 0}


def test_scoped_people_drops_a_person_absent_from_the_face_scope() -> None:
    """`view.people` must shrink with the pool (#2044): once `AccountScope.face_accounts`
    says who the asking accounts can read, a person held to no readable account is not a
    candidate `link_who` can name or link in A's trace, the same way their pictures are
    already out of A's pool."""
    from immich_memories.cli._ask_generation import _scoped_people
    from immich_memories.free_text.account_scope import AccountScope
    from immich_memories.free_text.library import LibraryPerson

    people = {
        "p-a": LibraryPerson("p-a", "Ada Example", None, None),
        "p-b": LibraryPerson("p-b", "Bo Example", None, None),
    }

    unscoped = _scoped_people(people, AccountScope())
    scoped = _scoped_people(people, AccountScope(face_accounts={"p-a": "primary"}))

    assert unscoped == people
    assert scoped == {"p-a": people["p-a"]}


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
    # #2045 Opus review: never "not possible" on a window that just hasn't been read yet.
    assert "VERDICT  needs preparation:" in result.output
    assert "not possible" not in result.output.lower()
    assert "Pool: " not in result.output


def test_the_preview_s_kept_translation_says_needs_preparation_not_not_possible(
    ask, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2045 (Opus review, BLOCKER): the web preview (the CLI's own `--dry-run --ask-trace`)
    must carry "needs preparation", not "not possible", so AskPanel can still offer to make
    the film, which then prepares the window for real."""
    ask.immich.unsynced_camera_shots = [("new-cat-0", FIRST + timedelta(days=1000))]

    def _never(**_kwargs):
        raise AssertionError("a dry run must never call the real preparation pipeline")

    monkeypatch.setattr(
        "immich_memories.analysis.editorial_preparation.prepare_editorial_annotations", _never
    )
    kept = tmp_path / "ask.json"

    result = ask("--ask", "our cat along the years", "--dry-run", "--ask-trace", str(kept))

    assert result.exit_code == 0, result.output
    record = json.loads(kept.read_text())
    assert record["verdict"] == "needs preparation"
    assert record["preparation"] is not None and record["preparation"]["pictures"] == 1
    # The route is "none" (no pool was read yet); the page keeps the button on the verdict.
    assert record["film"]["route"] == "none"


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


def _flaky_reader(valid_times: int) -> Any:
    """Valid on the first `valid_times` calls to the reading question, cut-shaped after.

    `read_request` asks the reading question in three field orders, retrying once per
    order when the shape is unusable; counting calls this way lands the reading on exactly
    `valid_times` usable answers of the three orders, however many retries that costs.
    """
    calls = {"n": 0}

    def answer(_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        if calls["n"] <= valid_times:
            return {"who": [], "when": ["along the years"], "where": [], "what": ["our cat"]}
        # WHY: stands in for the model server; a wrong shape is unusable, not empty.
        return {"who": "", "when": "", "where": "", "what": ""}

    return answer


def test_a_reader_that_cannot_read_the_request_fails_cleanly_not_with_a_traceback(ask) -> None:
    # Only the first of the three field-order answers is usable; the other two never
    # settle even after their retry, so the reading has 1 of 3 usable answers.
    answers = {**ANSWERS, "Split the owner's request": _flaky_reader(1)}

    result = ask("--ask", "our cat along the years", "--dry-run", answers=answers)

    assert result.exit_code != 0, result.output
    assert "couldn't read this request consistently" in result.output
    assert "1 of 3 answers usable" in result.output
    assert "Traceback" not in result.output


def test_two_of_three_usable_readings_still_translate_the_request(ask) -> None:
    # The first two field orders settle; the third fails even after its retry, so the
    # reading has 2 of 3 usable answers -- the behaviour before this fix, unchanged.
    answers = {**ANSWERS, "Split the owner's request": _flaky_reader(2)}

    result = ask("--ask", "our cat along the years", "--dry-run", answers=answers)

    assert result.exit_code == 0, result.output
    assert "VERDICT  possible" in result.output


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


def test_a_household_preview_counts_every_named_accounts_missing_pictures(
    tmp_path: Path, lexicon: WordNetLexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2044 + #2045: the window check reads every chosen account's own library, not just
    the primary's -- `AccessBoundClient`'s plain search stays on the primary alone, so
    discovery has to go through each account by name (`HouseholdWindows`)."""
    import yaml

    from immich_memories.cli import main
    from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-cat", "primary", 1, ())],
            PARTNER_KEY: [picture("q-cat", "partner", 2, ())],
        }
    ).install(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # WHY: the pinned WordNet corpus is a model download; this one holds the test's words.
    monkeypatch.setattr("immich_memories.cli._ask_generation.load_wordnet", lambda _path: lexicon)
    # `window_of` would otherwise ask for the whole library's years, which this fake
    # server does not answer; the fixture's own pictures sit in June 2025.
    dated = {
        **ANSWERS,
        "Give the date range": {"date_from": "2025-06-01", "date_to": "2025-06-30"},
    }
    monkeypatch.setattr(
        "immich_memories.cli._ask_generation.WireAsker", lambda *_a, **_k: QuestionAsker(dated)
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "immich": immich_config(),
                "tier": "full",
                "advanced": {
                    "llm": {
                        "enabled": True,
                        "base_url": "http://reader.invalid/v1",
                        "model": "small-reader",
                    }
                },
            }
        )
    )

    result = CliRunner().invoke(
        main,
        [
            "-c",
            str(config_path),
            "generate",
            "--ask",
            "our cat along the years",
            "--accounts",
            "primary,partner",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "2 pictures in this period aren't prepared yet" in result.output
