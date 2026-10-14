"""Render choices read from the finished film: quality, the fast preset, the fade colour, the language.

Quality is read from the encoder's own record: libx264 writes the options it encoded with
into every H.264 stream, so the film says which CRF and effort preset produced it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.features.cli_harness import UserHome, band_luma, basic_config, film_facts
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import QUIET_DAY, day_args, render_into

_MONTH = ("generate", "--start", "2025-07-01", "--end", "2025-07-31", "--include-photos")


def _x264_options(film: Path) -> dict[str, str]:
    """The options libx264 recorded in the film's video stream (its SEI user data)."""
    data = film.read_bytes()
    start = data.find(b"x264 - core")
    assert start >= 0, f"{film.name} was not encoded by libx264"
    record = data[start : data.find(b"\x00", start)].decode("latin-1")
    options = record.split(" - ", 2)[-1]
    return dict(item.split("=", 1) for item in options.split() if "=" in item)


def _encoding(options: dict[str, str]) -> tuple[str, ...]:
    """What a quality tier changes: the rate factor and the effort the encoder spent."""
    return tuple(options[key] for key in ("crf", "ref", "subme", "me", "rc_lookahead"))


def _config(home: UserHome, immich: LibraryServer, **output: str) -> dict:
    """The Basic install with output.quality left to the default unless `output` sets it."""
    config = basic_config(immich.base_url, immich.api_key, home)
    config["output"].pop("quality")
    config["output"].update(output)
    return config


def _render(home: UserHome, directory: Path, *args: str) -> Path:
    return render_into(home, directory, *day_args(QUIET_DAY), *args).film


@pytest.mark.feature("output.quality")
def test_quality_flag_encodes_the_film_as_the_config_tier_it_names(
    fresh_home: UserHome, immich: LibraryServer, tmp_path
):
    by_flag, by_config = {}, {}
    fresh_home.write_config(_config(fresh_home, immich))
    for word in ("high", "medium", "low"):
        film = _render(fresh_home, tmp_path / f"flag-{word}", "--quality", word)
        by_flag[word] = _encoding(_x264_options(film))
    for tier in ("high", "balanced", "fast"):
        fresh_home.write_config(_config(fresh_home, immich, quality=tier))
        by_config[tier] = _encoding(_x264_options(_render(fresh_home, tmp_path / f"cfg-{tier}")))

    assert by_flag["high"] == by_config["high"]
    assert by_flag["medium"] == by_config["balanced"]
    assert by_flag["low"] == by_config["fast"]
    # The three tiers are different encodes: high spends bits, fast spends less effort.
    crf = {tier: float(encoding[0]) for tier, encoding in by_config.items()}
    assert crf["high"] < crf["balanced"] == crf["fast"]
    assert by_config["fast"][1:] != by_config["balanced"][1:]
    assert int(by_config["fast"][1]) < int(by_config["balanced"][1])


@pytest.mark.feature("config.preset")
def test_preset_fast_fills_every_knob_left_unset_and_keeps_the_ones_set(
    fresh_home: UserHome, immich: LibraryServer, tmp_path
):
    preset = ("--preset", "fast", *day_args(QUIET_DAY))
    unset = _config(fresh_home, immich)
    unset["output"].pop("resolution")
    fresh_home.write_config(unset)
    shown = fresh_home.run("--preset", "fast", "config", "show", "title_screens", "hardware")
    filled = render_into(fresh_home, tmp_path / "filled", *preset).film
    fresh_home.write_config(_config(fresh_home, immich, quality="fast", resolution="1080p"))
    as_if_configured = _render(fresh_home, tmp_path / "configured")
    fresh_home.write_config(_config(fresh_home, immich, resolution="720p", quality="high"))
    kept = render_into(fresh_home, tmp_path / "kept", *preset).film
    without_preset = _render(fresh_home, tmp_path / "without")

    assert shown.returncode == 0, shown.explain()
    assert re.search(r"│ title_screens\.animated_background\s+│ false\s+│", shown.stdout), (
        shown.explain()
    )
    assert re.search(r"│ hardware\.encoder_preset\s+│ fast\s+│", shown.stdout), shown.explain()
    # Nothing set: the preset's 1080p and its fast encode, as if the config had said so.
    assert film_facts(filled).height == 1080
    assert _encoding(_x264_options(filled)) == _encoding(_x264_options(as_if_configured))
    # Resolution and quality set in config.yaml: the preset leaves both alone.
    assert film_facts(kept).height == 720
    assert _x264_options(kept)["crf"] == _x264_options(without_preset)["crf"]


@pytest.mark.feature("titles.fade-color")
def test_fade_color_sets_both_ends_of_this_film_and_leaves_the_saved_default(
    fresh_home: UserHome, immich: LibraryServer, tmp_path
):
    fresh_home.write_config(_config(fresh_home, immich))
    black = _render(fresh_home, tmp_path / "black", "--fade-color", "black")
    white = _render(fresh_home, tmp_path / "white", "--fade-color", "white")
    shown = fresh_home.run("config", "show", "title_screens.fade_color")

    def ends(film: Path) -> tuple[float, float]:
        last = film_facts(film).duration - 0.05
        return (
            band_luma(film, 0.0, top_fraction=1.0),
            band_luma(film, last, top_fraction=1.0),
        )

    assert all(luma < 16 for luma in ends(black)), ends(black)
    assert all(luma > 235 for luma in ends(white)), ends(white)
    # The flag was this render's: the configured default is still the built-in white.
    assert re.search(r"│ title_screens\.fade_color\s+│ white\s+│ default", shown.stdout), (
        shown.explain()
    )


def _month_title(home: UserHome, **env: str) -> str:
    result = home.run(
        *_MONTH, "--no-music", "--quiet", "--no-render", scripted_selection=True, env=env
    )
    assert result.returncode == 0, result.explain()
    title = re.search(r"^Title: (.+)$", result.stdout, re.M)
    assert title, result.explain()
    return title.group(1).strip()


@pytest.mark.feature("titles.locale")
def test_titles_follow_the_configured_locale_and_auto_follows_the_host(
    fresh_home: UserHome, immich: LibraryServer
):
    config = _config(fresh_home, immich)
    config["title_screens"] = {"locale": "fr"}
    fresh_home.write_config(config)
    configured = _month_title(fresh_home, LC_ALL="de_DE.UTF-8")
    config["title_screens"] = {"locale": "auto"}
    fresh_home.write_config(config)
    german_host = _month_title(fresh_home, LC_ALL="de_DE.UTF-8")
    english_host = _month_title(fresh_home, LC_ALL="en_US.UTF-8")

    # A configured language wins over the host's; auto reads the host's variables.
    assert configured == "Juillet 2025"
    assert german_host == "Juli 2025"
    assert english_host == "July 2025"
