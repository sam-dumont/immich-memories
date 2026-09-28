"""A music preview is the track the render would generate for this cut, heard before rendering."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from immich_memories.audio.cut_music_preview import preview_music_for_cut
from tests.test_revision_render import cut  # noqa: F401 - the saved-cut fixture


def test_the_preview_is_generated_from_the_cut_s_own_timeline_and_mood(cut, tmp_path, monkeypatch):  # noqa: F811
    params, attempt = cut
    params.config.musicgen.enabled = True
    asked: dict = {}

    async def mood_for_cut(config, attempt_dir, asset_ids):
        asked["mood_ids"] = asset_ids
        return SimpleNamespace(mood=SimpleNamespace(primary_mood="happy"))

    async def generate(**kwargs):
        asked.update(kwargs)
        track = kwargs["output_dir"] / "track.wav"
        track.write_bytes(b"RIFF")
        return SimpleNamespace(versions=[SimpleNamespace(full_mix=track)])

    # WHY: the text model and the music service are the external boundaries.
    monkeypatch.setattr("immich_memories.audio.cut_music_preview.mood_for_cut", mood_for_cut)
    monkeypatch.setattr(
        "immich_memories.audio.cut_music_preview.generate_music_for_video", generate
    )

    track = asyncio.run(preview_music_for_cut(params.config, attempt, tmp_path / "preview"))

    assert track == tmp_path / "preview" / "track.wav"
    assert asked["mood_ids"] == tuple(clip.asset.id for clip in params.clips)
    timeline = asked["timeline"]
    assert len(timeline.clips) == len(params.clips)
    assert {clip.mood for clip in timeline.clips} == {"happy"}
    assert asked["config"].num_versions == 1


def test_without_a_music_generator_the_preview_says_which_setting_enables_one(cut, tmp_path):  # noqa: F811
    import pytest

    from immich_memories.audio.cut_music_preview import PreviewUnavailable

    params, attempt = cut
    params.config.musicgen.enabled = False
    params.config.ace_step.enabled = False

    with pytest.raises(PreviewUnavailable, match="musicgen.enabled"):
        asyncio.run(preview_music_for_cut(params.config, attempt, tmp_path / "preview"))
