"""A stored warning is worded where it is read, and a stored English one still shows (#1962)."""

from __future__ import annotations

from immich_memories.generate_delivery import safe_delivery_message
from immich_memories.operational_warnings import JOINER, coded, render_warning
from immich_memories.tracking.models import DeliveryStatus
from tests.web_api_fixtures import api_client, config_in, save_run

RUN = "20261002_120000_bbbb"
OLD_ENGLISH = "uploaded film's tags did not stay"


def _run_page(tmp_path, locale: str) -> dict:
    config = config_in(tmp_path)
    config.title_screens.locale = locale
    save_run(
        config,
        RUN,
        cut=False,
        delivery_status=DeliveryStatus.PENDING,
        delivery_error=JOINER.join(
            [coded("not_uploaded", permissions="asset.upload"), OLD_ENGLISH]
        ),
        warnings=[coded("album_not_added_key", permission="albumAsset.create"), OLD_ENGLISH],
    )
    return api_client(config).get(f"/api/v1/runs/{RUN}").json()


def test_the_run_page_words_coded_warnings_in_the_films_language(tmp_path) -> None:
    page = _run_page(tmp_path, "fr")

    assert page["warnings"] == [
        "film non ajouté à l'album : la clé d'API n'a pas le droit albumAsset.create",
        OLD_ENGLISH,
    ]
    assert page["delivery_error"] == (
        f"non envoyé : la clé d'API n'a pas le droit asset.upload{JOINER}{OLD_ENGLISH}"
    )


def test_the_run_page_in_english_reads_as_it_always_did(tmp_path) -> None:
    page = _run_page(tmp_path, "en")

    assert page["warnings"][0] == "film not added to album: the key lacks albumAsset.create"
    assert page["warnings"][1] == OLD_ENGLISH


def test_a_delivery_warning_is_scrubbed_of_a_configured_secret_despite_its_encoding(
    tmp_path,
) -> None:
    config = config_in(tmp_path)
    config.immich.api_key = "k3y-very-secret-value"
    stored = coded("album_not_added_error", detail="Immich said no to k3y-very-secret-value")

    safe = safe_delivery_message(stored, config)

    assert "k3y-very-secret-value" not in safe
    assert render_warning(safe) == "film not added to album: Immich said no to ***"
