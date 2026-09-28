"""A still's banked det-v2 exposure answer is its det-v3 answer; a video's is not.

det-v3 changed how a video is read (eight frames, the strongest kept) and nothing about a
still, which is still decided on its preview by the same export. So a store written under
det-v2 owes the exposure head its videos again, and never its stills.
"""

from immich_memories.analysis.editorial_preparation import PreparationPorts
from immich_memories.analysis.editorial_preparation_detectors import (
    MARQO_HEAD,
    MARQO_ONNX_ID,
    MARQO_VERSION,
)
from immich_memories.config_models_editorial_preparation import EditorialPreparationConfig
from immich_memories.store.editorial_preparation import remember_head_rows
from tests.annotation_rows import annotation_store, read_rows
from tests.test_editorial_preparation import asset, preview, run
from tests.test_editorial_preparation_motion import prepared_video


def _exposure_row(asset_id, version, confidence):
    return {
        "asset_id": asset_id,
        "head": MARQO_HEAD,
        "version": version,
        "label": "no",
        "confidence": confidence,
        "encoder_key": MARQO_ONNX_ID,
        "decided_at": "2026-01-01T00:00:00+00:00",
    }


def test_a_banked_det_v2_still_is_not_read_again_and_a_video_is(tmp_path):
    remember_head_rows(
        annotation_store(),
        [_exposure_row("aa1", "det-v2", 0.12), _exposure_row("vv1", "det-v2", 0.2)],
    )
    owed = []

    # WHY: the detector worker runs the Marqo ONNX export in a subprocess; the test only
    # needs to know which sources preparation hands it, and to bank what it would answer.
    def detectors(**kwargs):
        owed.append({head: tuple(ids) for head, ids in kwargs["pending"].items()})
        remember_head_rows(
            kwargs["store"],
            [
                _exposure_row(asset_id, MARQO_VERSION, 0.3)
                for asset_id in kwargs["pending"].get(MARQO_HEAD, ())
            ],
        )
        return {}

    result = run(
        tmp_path,
        assets=[asset("aa1"), prepared_video("vv1")],
        ports=PreparationPorts(detectors=detectors),
        preparation_config=EditorialPreparationConfig(tier="no_captions"),
        head_versions={MARQO_HEAD: MARQO_VERSION},
        fetch_preview=lambda _: preview(),
    )

    assert owed == [{MARQO_HEAD: ("vv1",)}]
    assert result.complete
    answers = {
        row["asset_id"]: row["confidence"]
        for row in read_rows(annotation_store(), "head_facts")
        if row["head"] == MARQO_HEAD and row["version"] == MARQO_VERSION
    }
    # The still keeps the answer it was banked with; only the video was read again.
    assert answers == {"aa1": 0.12, "vv1": 0.3}
