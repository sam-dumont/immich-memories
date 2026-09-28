"""The special-days catalogue in the store, through its public faces."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from immich_memories.automation.catalogue import entries_from, load_catalogue, save_catalogue
from immich_memories.config_loader import Config
from immich_memories.db.bootstrap import SCHEMA_ENV, URL_ENV

# Every shape a catalogue holds: a judged day, an unjudged one, a year marker, and a
# canonical event a person curated (membership hash and all), plus a key no scan writes.
CATALOGUE = [
    {
        "day": "2019-06-12",
        "title": "A long evening out",
        "photos": 133,
        "window": ["2019-06-12T17:00:00", "2019-06-12T23:30:00"],
        "prompt_version": "v3",
        "app_version": "0.80.0",
        "hand_note": "kept as written",
    },
    {"unjudged": "2019-08-02", "photos": 40, "prompt_version": "v3", "app_version": "0.80.0"},
    {"scanned": 2019},
    {"day": "2020-01-05", "title": "", "what": "A walk", "photos": 12},
]


@pytest.fixture
def cli_store(store, monkeypatch):
    """The CLI's default store is this test's store, on either backend."""
    monkeypatch.setenv(URL_ENV, store.location.url)
    monkeypatch.setenv(SCHEMA_ENV, store.location.schema)
    return store


def _invoke(*args: str):
    from immich_memories.cli import main

    # WHY: the CLI group writes a starter config dir, loads the user's config file, and
    # reconfigures the process's root logger, which would leak into every later test.
    with (
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=Config()),
        patch("immich_memories.logging_config.configure_logging"),
    ):
        return CliRunner().invoke(main, list(args))


def _cli(*args: str) -> str:
    result = _invoke(*args)
    assert result.exit_code == 0, result.output
    return result.output


def test_the_catalogue_round_trips_verbatim(store):
    save_catalogue(CATALOGUE, store)

    assert load_catalogue(store) == CATALOGUE
    assert [str(entry.day) for entry in entries_from(load_catalogue(store))] == [
        "2019-06-12",
        "2020-01-05",
    ]

    save_catalogue(CATALOGUE[:1], store)

    assert load_catalogue(store) == CATALOGUE[:1]


def test_the_cli_exports_edits_and_imports_the_catalogue(cli_store, tmp_path):
    save_catalogue(CATALOGUE, cli_store)
    exported = tmp_path / "days.json"

    _cli("days-export", "--to", str(exported))
    edited = json.loads(exported.read_text())
    edited[0]["title"] = "A long evening, renamed"
    exported.write_text(json.dumps(edited))
    _cli("days-import", "--from", str(exported))

    assert load_catalogue(cli_store) == edited
    assert "A long evening, renamed" in _cli("days-due", "--on", "2026-06-12")


def test_the_cli_refuses_a_file_that_is_not_a_catalogue(cli_store, tmp_path):
    save_catalogue(CATALOGUE, cli_store)
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"day": "2019-06-12"}))

    result = _invoke("days-import", "--from", str(broken))

    assert result.exit_code == 1
    assert load_catalogue(cli_store) == CATALOGUE
