"""Warnings are a code plus params, worded in the reader's language (#1962)."""

from __future__ import annotations

import pytest

from immich_memories.operational_warnings import (
    coded,
    render_warning,
    render_warnings,
    scrub_warning,
)


def test_a_coded_warning_reads_the_same_in_english_as_the_old_text() -> None:
    stored = coded("delivery_incomplete", permissions="album.create, tag.asset")

    assert render_warning(stored) == "delivery incomplete: the key lacks album.create, tag.asset"


def test_a_coded_warning_is_worded_in_the_films_language() -> None:
    stored = coded("not_uploaded", permissions="asset.upload")

    assert render_warning(stored, "fr") == (
        "non envoyé : la clé d'API n'a pas le droit asset.upload"
    )


def test_a_warning_stored_before_codes_still_displays_as_it_was() -> None:
    old = "uploaded film's tags did not stay"

    assert render_warning(old, "fr") == old


def test_an_unknown_code_is_left_as_stored_rather_than_dropped() -> None:
    assert render_warning("warn.from_a_newer_release?a=1", "fr") == "warn.from_a_newer_release?a=1"


def test_a_joined_delivery_reason_words_each_warning() -> None:
    joined = "; ".join(
        [
            coded("not_uploaded", permissions="asset.upload"),
            "uploaded without provenance: the tag did not stay",
        ]
    )

    assert render_warning(joined) == (
        "not uploaded: the key lacks asset.upload; "
        "uploaded without provenance: the tag did not stay"
    )


def test_a_value_with_separators_survives_the_round_trip() -> None:
    detail = "timed out; retry & see https://x.example/a?b=c"
    stored = coded("album_not_added_error", detail=detail)

    assert "; " not in stored
    assert render_warning(stored) == f"film not added to album: {detail}"


def test_a_value_that_is_itself_coded_is_worded_too() -> None:
    stored = coded("gave_up", attempts=3, detail=coded("not_uploaded", permissions="asset.upload"))

    assert render_warning(stored, "fr") == (
        "Livraison à Immich abandonnée après 3 tentatives : "
        "non envoyé : la clé d'API n'a pas le droit asset.upload"
    )


def test_scrubbing_finds_a_secret_the_encoding_changed() -> None:
    stored = coded("album_not_added_error", detail="refused by https://immich.example/api")

    scrubbed = scrub_warning(stored, lambda text: text.replace("https://immich.example/api", "***"))

    assert render_warning(scrubbed) == "film not added to album: refused by ***"
    assert "immich.example" not in scrubbed


def test_scrubbing_old_text_scrubs_it_whole() -> None:
    assert scrub_warning("see secret-1", lambda t: t.replace("secret-1", "***")) == "see ***"


@pytest.mark.parametrize("locale", ["fr", "de", "ja", "xx"])
def test_render_warnings_keeps_order_and_count(locale: str) -> None:
    stored = [coded("delivery_incomplete", permissions="a"), "plain old text"]

    rendered = render_warnings(stored, locale)

    assert len(rendered) == 2 and rendered[1] == "plain old text"
