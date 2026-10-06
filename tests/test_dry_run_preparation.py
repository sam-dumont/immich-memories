"""`generate --dry-run` says what preparation the period still needs (#2154).

It used to print "coverage checked at selection" and nothing else, while the docs promise a
preview of the required preparation, the way the `--ask` dry run already gives one.
"""

from __future__ import annotations

from immich_memories.analysis.prepare_scope import unprepared_pictures
from immich_memories.config_loader import Config
from immich_memories.config_models_editorial_preparation import EditorialPreparationConfig
from tests.annotation_rows import add_rows, annotation_store

PRODUCER = Config().editorial.pixel_producer_key


def _metadata_only() -> Config:
    config = Config()
    config.editorial.preparation = EditorialPreparationConfig(tier="metadata_only")
    return config


def _measure(store, *asset_ids: str) -> None:
    add_rows(
        store,
        "pixel_facts_thresholds",
        {"name": "sharpness_p10", "value": 10.0, "producer_key": PRODUCER, "n": 1},
    )
    add_rows(
        store,
        "pixel_facts",
        *(
            {
                "asset_id": asset_id,
                "producer_key": PRODUCER,
                "sharpness": 50.0,
                "brightness": 120.0,
                "contrast": 40.0,
                "dark_fraction": 0.1,
                "bright_fraction": 0.1,
            }
            for asset_id in asset_ids
        ),
    )


def test_a_period_nothing_read_yet_needs_every_picture_prepared():
    needed = unprepared_pictures(_metadata_only(), annotation_store(), ["a", "b", "c"])

    assert needed.pictures == 3
    assert needed.of == 3


def test_pictures_already_prepared_are_not_counted():
    store = annotation_store()
    _measure(store, "a")

    needed = unprepared_pictures(_metadata_only(), store, ["a", "b", "c"])

    assert needed.pictures == 2
    assert "2 of 3 pictures in this period aren't prepared yet" in needed.line()


def test_a_prepared_period_says_so():
    store = annotation_store()
    _measure(store, "a", "b")

    needed = unprepared_pictures(_metadata_only(), store, ["a", "b"])

    assert needed.pictures == 0
    assert needed.line() == "all 2 pictures in this period are prepared"


def test_the_dry_run_prints_what_the_period_still_needs(capsys):
    from pathlib import Path
    from types import SimpleNamespace

    from immich_memories.cli._generation_preview import print_dry_run_preparation
    from immich_memories.processing.output_canvas import OutputCanvas

    _measure(annotation_store(), "a")
    print_dry_run_preparation(
        context=SimpleNamespace(product="monthly_highlights", label="June 2024", target_seconds=60),
        assets=[],
        photos=[SimpleNamespace(id=asset_id) for asset_id in ("a", "b")],
        output_canvas=OutputCanvas(width=1920, height=1080, orientation="landscape"),
        output_path=Path("/films/june.mp4"),
        config=_metadata_only(),
        music=None,
        no_music=True,
        should_upload=False,
        album_name=None,
    )

    out = capsys.readouterr().out
    assert "Preparation: 1 of 2 pictures in this period aren't prepared yet (pixel facts 1)" in out
