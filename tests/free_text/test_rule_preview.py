"""The rule preview: which of the editor's rules would drop pool pictures, before anything renders.

Every picture, caption and flag here is invented. The facts are banked in a real store, and the
preview reads them through the run's own line reader and rule functions: nothing is mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from immich_memories.analysis.editorial_runtime_evidence import AnnotationReadings
from immich_memories.analysis.editorial_source import library_source_scope
from immich_memories.api.models import Asset
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.free_text.rule_preview import preview_rules
from immich_memories.timeperiod import DateRange
from tests.annotation_rows import add_rows

CONFIG = Config()
EDITORIAL = CONFIG.editorial
START = datetime(2021, 3, 1, 10, tzinfo=UTC)


def _photo(asset_id: str, minutes: int, *, name: str = "", pixels: int = 3000) -> Asset:
    at = START + timedelta(minutes=minutes)
    return Asset(
        id=asset_id,
        type="IMAGE",
        file_created_at=at,
        file_modified_at=at,
        updated_at=at,
        original_file_name=name or f"IMG_{asset_id}.JPG",
        width=pixels,
        height=pixels * 3 // 4,
    )


def _caption(asset_id: str, text: str) -> dict[str, str]:
    return {"asset_id": asset_id, "model": EDITORIAL.description_model, "text": text}


def _pool() -> list[Asset]:
    store = open_store()
    pool = [
        _photo("cat-1", 0),
        _photo("cat-2", 30),
        _photo("screen-1", 60),
        _photo("held-1", 90),
        _photo("bandage-1", 120),
        # The chat's downscale of cat-2: same camera name, same instant, fewer pixels.
        _photo("copy-1", 30, name="IMG_cat-2.JPG", pixels=2048),
    ]
    add_rows(
        store,
        "descriptions",
        _caption("cat-1", "A black cat sleeping on a sofa"),
        _caption("cat-2", "A black cat on a windowsill"),
        _caption("screen-1", "A black cat on a laptop"),
        _caption("held-1", "A black cat and a person on a bed"),
        _caption("bandage-1", "A black cat with a bandage on its paw"),
    )
    add_rows(
        store,
        "head_facts",
        {
            "asset_id": "screen-1",
            "head": "doc_docling",
            "version": EDITORIAL.head_versions["doc_docling"],
            "label": "screenshot_from_computer",
        },
    )
    add_rows(
        store, "asset_flags", {"asset_id": "held-1", "flag": "never_auto", "source": "nsfw_marqo"}
    )
    return pool


def _preview(pool: list[Asset]):
    window = DateRange(start=START, end=START + timedelta(days=1))
    scope = library_source_scope(None, CONFIG, (window,), accept_any_provenance=True)
    readings = AnnotationReadings(store=open_store(), config=CONFIG, people={})
    return preview_rules(pool, scope=scope, readings=readings, audience="family")


def test_each_rule_that_would_drop_pool_pictures_is_listed_with_its_pictures() -> None:
    preview = _preview(_pool())

    dropped = {drop.rule: drop.asset_ids for drop in preview.drops}
    assert dropped == {
        "another file of the same picture": ("copy-1",),
        "screens and documents": ("screen-1",),
        "held for review": ("held-1",),
        "medical care": ("bandage-1",),
    }
    assert (preview.checked, preview.passed) == (6, 2)


def _video(asset_id: str, minutes: int, *, starred: bool = False) -> Asset:
    at = START + timedelta(minutes=minutes)
    return Asset(
        id=asset_id,
        type="VIDEO",
        file_created_at=at,
        file_modified_at=at,
        updated_at=at,
        original_file_name=f"VID_{asset_id}.MOV",
        is_favorite=starred,
        width=1920,
        height=1080,
        duration="0:00:12.000",
    )


def test_a_video_whose_frames_miss_the_subject_is_dropped_unless_starred() -> None:
    clips = [_video("wall-1", 0), _video("wall-starred", 30, starred=True)]
    add_rows(
        open_store(),
        "head_facts",
        *(
            {
                "asset_id": clip.id,
                "head": "clip_frames",
                "version": "frame_kind-public-v1/8-frames",
                "label": "subject_often_missing",
            }
            for clip in clips
        ),
    )

    preview = _preview(clips)

    assert [(drop.rule, drop.asset_ids) for drop in preview.drops] == [
        ("video frames miss the subject", ("wall-1",))
    ]


def test_rules_known_only_while_cutting_are_named_without_a_count() -> None:
    preview = _preview(_pool())

    assert [note.rule for note in preview.at_cut] == [
        "who sees it",
        "look-alikes",
        "capture spacing",
    ]
    assert "family film" in preview.at_cut[0].why
    assert [note.rule for note in preview.lifted] == ["provenance", "standing"]
