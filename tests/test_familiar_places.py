"""Coordinate validity and captions that do not need library history."""

import pytest


@pytest.mark.parametrize(
    "point", [(None, 4.362), (50.843, None), (0, 0), (91, 4), (float("nan"), 4)]
)
def test_invalid_gps_cannot_be_a_familiar_place(point):
    from immich_memories.analysis.familiar_places import valid_coordinates

    assert not valid_coordinates(*point)


@pytest.mark.parametrize("privacy,overlay", [(True, True), (False, False)])
def test_no_history_scan_when_places_are_hidden_or_anonymized(tmp_path, privacy, overlay):
    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_captions import prepare_location_captions

    class NoNetwork:
        def search_metadata(self, **kwargs):
            pytest.fail("this render must not inspect real GPS history")

    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "memory.mp4",
        config=Config(),
        client=NoNetwork(),
        privacy_mode=privacy,
        add_place_overlay=overlay,
    )
    assert prepare_location_captions(params, []) == []
