"""The film name a person sees is in the film's language; the file on disk stays English."""

from __future__ import annotations

import json
import re
from email import message_from_bytes
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from immich_memories.api.film_label import FilmLabel
from immich_memories.api.immich import ImmichClient
from immich_memories.config.loader import Config
from immich_memories.filename_builder import album_film_path, build_memory_output_path
from immich_memories.operations.shown_film_name import (
    content_disposition,
    safe_display_name,
    shown_film_name,
    shown_film_name_for,
)
from immich_memories.timeperiod import calendar_year
from tests.immich_fakes import ImmichWire, request_problems
from tests.web_api_fixtures import api_client, config_in, save_run

DISK = "camille_monthly_highlights_2025_a1b2c3d4.mp4"


def _config(locale: str) -> Config:
    config = Config()
    config.title_screens.locale = locale
    return config


def _shown(locale: str, disk: str = DISK, **given) -> str:
    return shown_film_name_for(
        _config(locale),
        disk,
        memory_type=given.pop("memory_type", "monthly_highlights"),
        person_name=given.pop("person_name", "Camille"),
        **given,
    )


def test_a_french_film_is_shown_in_french_with_its_recipe_hash():
    shown = _shown("fr")

    assert shown.startswith("Camille ")
    assert shown.endswith(" 2025 a1b2c3d4.mp4")
    assert "monthly" not in shown.lower()


def test_an_english_film_is_shown_as_it_is_named_on_disk():
    assert _shown("en") == DISK


def test_a_custom_file_name_is_left_alone():
    assert _shown("fr", "my film.mp4") == "my film.mp4"


@pytest.mark.parametrize("locale", ["fr", "ja"])
def test_the_name_on_disk_never_depends_on_the_film_language(locale, tmp_path):
    # The builders take no language: a French or a Japanese film gets the English name.
    path = build_memory_output_path(
        output_dir=tmp_path,
        person_names=["camille"],
        memory_type="year_in_review",
        date_range=calendar_year(2025),
        container="mp4",
    )
    assert path.name == "camille_year_in_review_2025.mp4"
    assert album_film_path(tmp_path, "Summer 2025", "mp4").name == "album_summer_2025.mp4"
    assert _shown(locale, path.name, memory_type="year_in_review") != path.name


def test_a_japanese_film_keeps_its_letters_and_is_filesystem_safe():
    shown = _shown("ja", person_name="さくら")

    assert shown.startswith("さくら ")
    assert shown.endswith(" 2025 a1b2c3d4.mp4")
    assert len(shown.encode()) <= 255


@pytest.mark.parametrize("locale", ["fr", "de", "ja", "ru", "zh-Hans", "ko", "pt-BR"])
def test_the_shown_name_is_safe_in_every_locale(locale):
    shown = _shown(locale, person_name='A/B\\C:D*E?F"G<H>I|J\x00K‮')

    assert not re.search(r'[/\\:*?"<>|\x00-\x1f\x7f‮]', shown)
    assert shown.endswith("a1b2c3d4.mp4")


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("a/b\\c:d", "a b c d"),
        ('x*y?z"<>|', "x y z"),
        ("tab\there\nnewline", "tab here newline"),
        ("fake‮txt.exe", "faketxt.exe"),
        ("..hidden..", "hidden"),
        ("  spaced   out  ", "spaced out"),
        ("é", "é"),
    ],
)
def test_safe_display_name_strips_what_a_filesystem_refuses(raw, safe):
    assert safe_display_name(raw) == safe


def test_a_long_name_is_capped_in_bytes_without_splitting_a_letter_or_losing_the_hash():
    shown = _shown("ja", person_name="桜" * 300)

    assert len(shown.encode()) <= 255
    assert shown.endswith(" 2025 a1b2c3d4.mp4")
    assert safe_display_name("桜" * 300, max_bytes=10) == "桜桜桜"


def test_an_album_film_shows_its_type_in_the_film_language():
    shown = shown_film_name(
        "album_summer_trip.mp4",
        memory_type="album",
        type_label="Album",
        people=None,
        locale="fr",
    )
    assert shown == "Album summer trip.mp4"


def test_the_download_header_carries_the_shown_name_and_an_ascii_fallback():
    header = content_disposition("Camille Année en revue 2025 a1b2c3d4.mp4", DISK)

    assert header.startswith(f"attachment; filename=\"{DISK}\"; filename*=UTF-8''")
    assert (
        unquote(header.split("filename*=UTF-8''")[1]) == "Camille Année en revue 2025 a1b2c3d4.mp4"
    )
    assert header.isascii()


def test_a_plain_name_needs_no_extended_filename():
    assert content_disposition(DISK, DISK) == f'attachment; filename="{DISK}"'


RUN = "20261002_120000_aaaa"


def test_a_french_runs_download_is_named_in_french_and_stays_english_on_disk(tmp_path):
    config = config_in(tmp_path)
    config.title_screens.locale = "fr"
    path = tmp_path / "camille_monthly_highlights_2025_a1b2c3d4.mp4"
    path.write_bytes(b"film")
    save_run(
        config, RUN, status="completed", output_path=str(path), person_name="Camille", cut=True
    )

    response = api_client(config).get(f"/api/v1/runs/{RUN}/download")

    header = response.headers["content-disposition"]
    assert f'filename="{path.name}"' in header
    shown = unquote(header.split("filename*=UTF-8''")[1])
    assert shown.startswith("Camille ") and shown.endswith(" 2025 a1b2c3d4.mp4")
    assert shown != path.name
    assert header.isascii()
    # The file and the run's folder keep the names scripts read.
    assert path.read_bytes() == b"film"
    assert (config.cache.cache_path / "editorial-runs" / RUN).is_dir()


def test_an_english_runs_download_is_named_as_on_disk(tmp_path):
    config = config_in(tmp_path)
    path = tmp_path / DISK
    path.write_bytes(b"film")
    save_run(config, RUN, status="completed", output_path=str(path), person_name="Camille")

    header = api_client(config).get(f"/api/v1/runs/{RUN}/download").headers["content-disposition"]

    assert header == f'attachment; filename="{DISK}"'


def _form_of(request: httpx.Request) -> tuple[dict[str, str], str]:
    """The text fields of a multipart upload, and the file part's name."""
    raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n"
    message = message_from_bytes(raw + request.content)
    fields: dict[str, str] = {}
    file_name = ""
    for part in message.get_payload():
        name = part.get_param("name", header="content-disposition")
        if part.get_filename() is not None:
            file_name = part.get_filename()
            fields[name] = "<binary>"
        else:
            fields[name] = part.get_payload(decode=True).decode()
    return fields, file_name


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["v2", "v3"])
async def test_immich_is_sent_the_french_name_while_the_file_on_disk_keeps_its_own(
    version, tmp_path: Path
):
    film = tmp_path / DISK
    film.write_bytes(b"film")
    sent: list[tuple[dict[str, str], str, list[str]]] = []

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/assets") and request.method == "POST":
            form, file_name = _form_of(request)
            problems = request_problems(
                "POST", request.url.path, {}, None, form=form, releases=_RELEASES[version]
            )
            sent.append((form, file_name, problems))
            return httpx.Response(201, json={"id": "asset-1", "status": "created"})
        return httpx.Response(200, json={})

    # WHY: Immich's upload endpoint, checked against the OpenAPI contract of the release.
    wire = ImmichWire(serve, releases=_RELEASES[version])
    client = ImmichClient("https://immich.test", "key", api_version=version)
    client._client = httpx.AsyncClient(base_url="https://immich.test", transport=wire.transport)
    shown = "Camille Moments du mois 2025 a1b2c3d4.mp4"
    async with client:
        await client.albums.upload_asset(film, shown_name=shown)

    form, file_name, problems = sent[0]
    assert problems == []
    assert form["filename"] == shown
    assert file_name == shown
    assert film.read_bytes() == b"film" and film.name == DISK


_RELEASES = {"v2": ("v2.7.5",), "v3": ("v3.2.2",)}


def test_the_label_carries_the_name_through_a_french_run(tmp_path):
    from immich_memories.operations.film_labelling import label_for_params

    class Params:
        config = _config("fr")
        memory_type = "monthly_highlights"
        date_start = None
        date_end = None
        editorial_attempt_dir = None
        title = None
        person_name = "Camille"
        memory_preset_params = None

    label = label_for_params(Params(), tmp_path / DISK)

    assert isinstance(label, FilmLabel)
    assert label.file_name and label.file_name != DISK
    assert json.dumps(label.file_name, ensure_ascii=False).count("a1b2c3d4") == 1
