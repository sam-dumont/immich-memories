"""Changing v1 producer semantics requires a new version and an explicit migration decision."""

import hashlib
import json
from pathlib import Path

from immich_memories.analysis import editorial_preparation_detectors as detectors
from immich_memories.analysis.editorial_clip_frames import CLIP_FRAMES_VERSION
from immich_memories.analysis.editorial_preparation_detector_frames import FRAME_WIDTH, FRAMES
from immich_memories.analysis.editorial_preparation_heads import PUBLIC_HEAD_VERSIONS
from immich_memories.config_models_editorial_preparation import EditorialPreparationConfig
from immich_memories.db.tables import head_facts
from immich_memories.triage import encoder, preprocess


def current_contract():
    bundle = EditorialPreparationConfig().head_bundle_path
    return {
        "contract": "detector-facts-v1",
        "primary_key": [column.name for column in head_facts.primary_key],
        "fields": [column.name for column in head_facts.columns],
        "versions": PUBLIC_HEAD_VERSIONS
        | detectors.DETECTOR_VERSIONS
        | {"clip_frames": CLIP_FRAMES_VERSION},
        "dino": {
            "model": encoder.DINOV2_SMALL_ID,
            "sha256": encoder.DINOV2_SMALL_ONNX_SHA256,
            "preprocess": preprocess.PREPROCESS_VERSION,
            "layout": encoder.LAYOUT_VERSION,
            "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        },
        "marqo": {
            "model": detectors.MARQO_ONNX_ID,
            "sha256": detectors.MARQO_ONNX_SHA256,
            "classes": list(detectors.MARQO_CLASSES),
            "side": detectors.MARQO_SIDE,
            "equivalent_stills": detectors.MARQO_STILL_EQUIVALENT,
        },
        "docling": {
            "model": detectors.DOCLING_REPO,
            "revision": detectors.DOCLING_REVISION,
            "classes": list(detectors.DOCLING_LABELS),
        },
        "sampling": {"frames": FRAMES, "width": FRAME_WIDTH},
    }


def test_v1_pins_payload_keys_models_labels_and_sampling():
    frozen = Path(__file__).parent / "fixtures/detector-cache-v1.json"
    assert current_contract() == json.loads(frozen.read_text()), (
        "A changed detector contract needs a new producer version and a documented compatibility "
        "migration. Do not silently overwrite the v1 snapshot."
    )


def test_switching_tiers_preserves_banked_detector_versions_and_gpu_reads():
    from immich_memories.analysis.editorial_shareability import load_detector_heads
    from immich_memories.config_loader import Config
    from immich_memories.config_tiers import apply_tier
    from tests.annotation_rows import add_rows, annotation_store

    config = Config(tier="gpu")
    versions = dict(config.editorial.head_versions)
    store = annotation_store()
    add_rows(
        store,
        "head_facts",
        *[
            {"asset_id": "picture", "head": head, "version": versions[head], "label": label}
            for head, label in (
                ("nsfw_marqo", "yes"),
                ("doc_docling", "table"),
                ("uncovered_person", "no"),
            )
        ],
    )
    assert (
        load_detector_heads(store, ["picture"], config.editorial.active_head_versions)["picture"][
            "nsfw_marqo"
        ]
        == "yes"
    )
    config.tier = "basic"
    apply_tier(config)
    assert config.tier == "basic"
    assert load_detector_heads(store, ["picture"], config.editorial.active_head_versions) == {
        "picture": {"uncovered_person": "no"}
    }
    config.tier = "gpu"
    apply_tier(config)
    assert config.editorial.head_versions == versions
    assert (
        load_detector_heads(store, ["picture"], config.editorial.active_head_versions)["picture"][
            "doc_docling"
        ]
        == "table"
    )


def test_a_live_photo_clip_reads_the_same_corrected_people_head_as_its_still():
    """#2079: the clip's detector rows go through the corroboration the annotation read applies,
    so a people head with no face behind it reads "none" on both."""
    from immich_memories.analysis.editorial_shareability import load_detector_heads
    from tests.annotation_rows import add_rows, annotation_store

    store = annotation_store()
    add_rows(
        store,
        "face_boxes",
        {"asset_id": "still", "named": False, "x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2},
    )
    add_rows(
        store,
        "head_facts",
        {"asset_id": "clip", "head": "people", "version": "public-v1", "label": "group"},
        {"asset_id": "still", "head": "people", "version": "public-v1", "label": "group"},
    )

    heads = load_detector_heads(store, ["clip", "still"], {"people": "public-v1"})

    assert heads["clip"]["people"] == "none"
    assert heads["still"]["people"] == "group"


def _live_photos(store, *pairs: tuple[str, str]) -> None:
    from tests.annotation_rows import add_rows

    add_rows(
        store,
        "annotation_assets",
        *({"asset_id": still, "live_photo_video_id": clip} for still, clip in pairs),
    )
    add_rows(
        store,
        "head_facts",
        *(
            {"asset_id": clip, "head": "people", "version": "public-v1", "label": "group"}
            for _still, clip in pairs
        ),
    )


def _face_on(store, asset_id: str) -> None:
    from tests.annotation_rows import add_rows

    add_rows(
        store,
        "face_boxes",
        {"asset_id": asset_id, "named": True, "x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2},
    )


def test_a_clip_read_alone_takes_its_still_face_as_its_own():
    """#2079: Immich reads faces on the still, never on its motion clip, and a film run reads
    the clips on their own. A clip's people head is backed by its still's face box; a clip
    whose still has none is lowered once the scope holds face data at all."""
    from immich_memories.analysis.editorial_shareability import load_detector_heads
    from tests.annotation_rows import annotation_store

    store = annotation_store()
    _live_photos(store, ("still-a", "clip-a"), ("still-b", "clip-b"))
    _face_on(store, "still-a")

    heads = load_detector_heads(store, ["clip-a", "clip-b"], {"people": "public-v1"})

    assert heads["clip-a"]["people"] == "group"
    assert heads["clip-b"]["people"] == "none"


def test_a_clip_read_with_its_still_keeps_the_still_face():
    """#2079: the picture-holds read (stills and clips together) must not lower a clip whose
    own still carries the face box."""
    from immich_memories.analysis.editorial_shareability import load_detector_heads
    from tests.annotation_rows import annotation_store

    store = annotation_store()
    _live_photos(store, ("still-a", "clip-a"))
    _face_on(store, "still-a")

    heads = load_detector_heads(store, ["still-a", "clip-a"], {"people": "public-v1"})

    assert heads["clip-a"]["people"] == "group"


def test_a_clip_whose_still_immich_names_now_keeps_its_people_head():
    """#2079: a face recognised in Immich after `prepare` has no stored box; the still it was
    found on names somebody now, and that backs its clip as it backs the still."""
    from immich_memories.analysis.editorial_shareability import load_detector_heads
    from tests.annotation_rows import annotation_store

    store = annotation_store()
    _live_photos(store, ("still-a", "clip-a"), ("still-late", "clip-late"))
    _face_on(store, "still-a")

    heads = load_detector_heads(
        store, ["clip-a", "clip-late"], {"people": "public-v1"}, named_now={"still-late"}
    )

    assert heads["clip-late"]["people"] == "group"


def test_named_now_reads_the_people_immich_names_on_each_picture():
    """#2079: a film run hands the clip read the pictures Immich names somebody on now."""
    from types import SimpleNamespace

    from immich_memories.analysis.editorial_shareability import named_now_of

    def asset(asset_id: str, *names: str | None) -> SimpleNamespace:
        return SimpleNamespace(id=asset_id, people=[SimpleNamespace(name=n) for n in names])

    assets = [asset("named", "Someone"), asset("unnamed", "  ", None), asset("nobody")]

    assert named_now_of(assets) == {"named"}
