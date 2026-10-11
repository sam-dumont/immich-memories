"""Which pictures the web UI serves, what runs and reports keep to themselves, sharing levels."""

from __future__ import annotations

import re
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import CAST
from tests.features.cli_harness import CliResult, UserHome, basic_config
from tests.features.served_app import ServedApp, served_app
from tests.integration.features.library import (
    GARDEN_DAY,
    QUIET_DAY,
    RenderedRun,
    day_args,
    left_out_on,
    shipped_on,
)

# ── thumbnails in the web UI ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def two_account_app(
    tmp_path_factory: pytest.TempPathFactory, fake_immich: FakeImmichServer
) -> Iterator[tuple[UserHome, ServedApp]]:
    """The served app over the fixture library, with a second account configured."""
    home = UserHome(tmp_path_factory.mktemp("two-accounts"))
    config = basic_config(fake_immich.base_url, fake_immich.api_key, home)
    config["immich"]["accounts"] = {
        "partner": {"url": fake_immich.base_url, "api_key": fake_immich.partner_api_key}
    }
    home.write_config(config)
    with served_app(home) as app:
        yield home, app


@pytest.mark.feature("privacy.thumbnails-scoped")
def test_the_ui_serves_only_pictures_a_configured_account_reads_even_from_its_cache(
    two_account_app: tuple[UserHome, ServedApp],
):
    home, app = two_account_app
    readable = shipped_on(GARDEN_DAY)[0].asset_id
    foreign = "zz-not-in-any-account"

    with app.client() as browser:
        served = browser.get(f"/api/v1/assets/{readable}/thumbnail", params={"size": "preview"})
        unknown = browser.get(f"/api/v1/assets/{foreign}/thumbnail", params={"size": "preview"})
        # The bytes the app cached for the readable picture, filed under the foreign id.
        cached = list((home.root / ".immich-memories" / "cache").rglob(f"*{readable}_*.jpg"))
        assert cached, "the served picture was cached"
        for path in cached:
            planted = path.parent.parent / foreign[:2] / path.name.replace(readable, foreign)
            planted.parent.mkdir(exist_ok=True)
            shutil.copyfile(path, planted)
        from_cache = [
            browser.get(f"/api/v1/assets/{foreign}/thumbnail", params={"size": size})
            for size in ("preview", "thumbnail")
        ]

    assert served.status_code == 200, served.text
    assert served.headers["content-type"] == "image/jpeg"
    assert served.content[:2] == b"\xff\xd8"
    assert unknown.status_code == 404
    assert [response.status_code for response in from_cache] == [404, 404]


# ── configured values in errors, logs and reports ────────────────────────────

SENTINELS = {
    "password": "FEATURE-LOGIN-PASSWORD-61d0",
    "trigger": "FEATURE-TRIGGER-TOKEN-0b7e5c1d9a2f4e6b8c0d",
    "llm": "FEATURE-LLM-KEY-a93f",
    "notify": "FEATURE-NOTIFY-TOKEN-4e28",
    "wrong_key": "FEATURE-WRONG-IMMICH-KEY-c5b1",
}


def _leaks(text: str, values: dict[str, str]) -> list[str]:
    return [name for name, value in values.items() if value in text]


@pytest.mark.feature("privacy.config-values-never-logged")
def test_no_configured_secret_reaches_output_logs_files_or_reports(
    tmp_path, fake_immich: FakeImmichServer
):
    home = UserHome(tmp_path / "home")
    config = basic_config(fake_immich.base_url, fake_immich.api_key, home)
    config["advanced"] |= {
        "auth": {
            "enabled": True,
            "provider": "basic",
            "username": "admin",
            "password": SENTINELS["password"],
        },
        "server": {"trigger_token": SENTINELS["trigger"]},
        "llm": {"enabled": False, "api_key": SENTINELS["llm"]},
        "notifications": {
            "enabled": False,
            "urls": [f"json://user:{SENTINELS['notify']}@notify.invalid"],
        },
    }
    home.write_config(config)
    secrets = SENTINELS | {"immich_key": fake_immich.api_key}
    bundle = tmp_path / "report.zip"

    cut = home.run(*day_args(QUIET_DAY), "--no-render", scripted_selection=True)
    run_id = re.findall(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})", cut.output)[0]
    printed: list[CliResult] = [
        cut,
        home.run("runs", "show", run_id),
        home.run("report", run_id),
        home.run("report", run_id, "--json"),
        home.run("report", run_id, "--bundle", str(bundle)),
        home.run("preflight", scripted_selection=True),
        # A key Immich refuses, given the way an operator overrides one: the errors.
        home.run("config", "test", env={"IMMICH_MEMORIES_IMMICH__API_KEY": SENTINELS["wrong_key"]}),
        home.run(
            *day_args(QUIET_DAY),
            "--no-render",
            scripted_selection=True,
            env={"IMMICH_MEMORIES_IMMICH__API_KEY": SENTINELS["wrong_key"]},
        ),
    ]
    with zipfile.ZipFile(bundle) as archive:
        reported = "\n".join(
            archive.read(name).decode("utf-8", "replace") for name in archive.namelist()
        )
    written = {
        path: path.read_bytes().decode("latin-1")
        for path in home.root.rglob("*")
        if path.is_file() and path != home.config_path
    }

    assert printed[-2].returncode != 0 and printed[-1].returncode != 0, "the wrong key fails"
    assert {result.args[:2]: _leaks(result.output, secrets) for result in printed} == {
        result.args[:2]: [] for result in printed
    }
    assert _leaks(reported, secrets) == []
    assert {path: hits for path, text in written.items() if (hits := _leaks(text, secrets))} == {}


# ── report: library details ──────────────────────────────────────────────────


def _report_texts(home: UserHome, run: RenderedRun, bundle: Path) -> dict[str, str]:
    """The pasted report, its JSON and every file of its bundle."""
    texts = {
        "markdown": home.run("report", run.run_id).stdout,
        "json": home.run("report", run.run_id, "--json").stdout,
    }
    home.run("report", run.run_id, "--bundle", str(bundle))
    with zipfile.ZipFile(bundle) as archive:
        texts |= {
            name: archive.read(name).decode("utf-8", "replace") for name in archive.namelist()
        }
    return texts


# A number as the report would write one, bounded the way its redaction bounds them.
_NUMBER = re.compile(r"(?<![0-9A-Za-z.])-?\d+\.\d+")


def _coordinates_in(text: str, coordinates: set[float]) -> list[str]:
    """Each number in `text` that is one of these coordinates, to 2, 3 or 4 places.

    A whole number, not a substring: "4.36" sits inside timings such as 14.3607 or
    704.36, which are no place. The fixture's 4 places followed by float noise
    (4.362400000001) still count.
    """
    return [
        number
        for number in _NUMBER.findall(text)
        for coordinate in coordinates
        if number.lstrip("-") in {f"{coordinate:.2f}", f"{coordinate:.3f}"}
        or number.lstrip("-").startswith(f"{coordinate:.4f}")
    ]


@pytest.mark.feature("report.redaction-library-details")
def test_the_report_names_no_person_place_or_coordinates(
    library_home: UserHome, garden_film: RenderedRun, tmp_path
):
    pictures = shipped_on(GARDEN_DAY)
    people = sorted({name for picture in pictures for name in picture.people})
    places = sorted({p.place.city for p in pictures} | {p.place.country for p in pictures})
    coordinates = {p.place.latitude for p in pictures} | {p.place.longitude for p in pictures}
    assert people and places, "the filmed pictures carry people and a place"
    assert set(people) <= set(CAST)

    texts = _report_texts(library_home, garden_film, tmp_path / "details.zip")

    for name, text in texts.items():
        found = [word for word in people + places if re.search(rf"\b{re.escape(word)}\b", text)]
        found += _coordinates_in(text, coordinates)
        assert found == [], name


@pytest.mark.feature("report.redaction-library-details")
def test_the_report_turns_asset_ids_into_report_local_hashes(
    library_home: UserHome, garden_film: RenderedRun, tmp_path
):
    ids = [picture.asset_id for picture in shipped_on(GARDEN_DAY)] + left_out_on(GARDEN_DAY)
    # The run's own logs name its pictures: what the report has to hash.
    assert any(asset_id in garden_film.result.output for asset_id in ids)

    texts = _report_texts(library_home, garden_film, tmp_path / "ids.zip")

    assert re.search(r"\bid-[0-9a-f]{16}\b", texts["markdown"])
    for name, text in texts.items():
        assert [asset_id for asset_id in ids if asset_id in text] == [], name


# ── sharing levels ───────────────────────────────────────────────────────────


@pytest.mark.feature("sharing.levels")
@pytest.mark.parametrize(("flag", "printed"), [("just-us", "just us"), ("family", "family")])
def test_runs_show_prints_the_sharing_level_a_cut_was_made_for(
    library_home: UserHome, flag: str, printed: str
):
    cut = library_home.run(
        *day_args(QUIET_DAY), "--sharing", flag, "--no-render", scripted_selection=True
    )
    assert cut.returncode == 0, cut.explain()
    run_id = re.findall(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})", cut.output)[0]

    shown = library_home.run("runs", "show", run_id)

    assert shown.returncode == 0, shown.explain()
    assert f"Sharing: {printed}" in shown.stdout
