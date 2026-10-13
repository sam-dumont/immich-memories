"""A film's generated soundtrack is one piece of music (#2472).

The music is planned from the film's real length, a long film's takes share one
musical identity (caption, style, BPM, key, seed lineage) and come from one
backend, and MusicGen gets one scene per chapter rather than one per clip.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from immich_memories.audio.generators import ace_step_captions
from immich_memories.audio.generators.base import (
    GenerationRequest,
    GenerationResult,
    MusicGenerator,
)
from immich_memories.audio.music_generator_models import ClipMood, VideoTimeline
from immich_memories.audio.music_pipeline import MusicPipeline
from tests.generated_audio_fixtures import write_audio
from tests.test_ace_step_block_duration import ace_boundary  # noqa: F401 - pytest fixture

PHOTO_SECONDS = 3.5


def _photo_film(photos: int, *, film_seconds: float | None) -> VideoTimeline:
    timeline = VideoTimeline.from_clips(
        clips=[(PHOTO_SECONDS, "happy", None)] * photos,
        title_duration=3.5,
        ending_duration=4.0,
    )
    timeline.film_duration = film_seconds
    return timeline


class RecordingGenerator(MusicGenerator):
    """Writes a short valid waveform per request and keeps the requests."""

    def __init__(self, name: str = "Gen", *, max_take: int | None = None, fail: bool = False):
        self._name = name
        self._max_take = max_take
        self._fail = fail
        self.requests: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_take_seconds(self) -> int | None:
        return self._max_take

    async def is_available(self) -> bool:
        return True

    async def generate(
        self, request: GenerationRequest, progress_callback: Any | None = None
    ) -> GenerationResult:
        self.requests.append(request)
        if self._fail:
            raise RuntimeError("down")
        out = request.output_dir / f"{self._name}_{request.variation_index}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_audio(out, 0.3)
        return GenerationResult(
            audio_path=out,
            duration_seconds=float(request.duration_seconds),
            prompt="caption",
            backend_name=self._name,
            metadata={"bpm": 96},
        )


def _fake_join(blocks, target, output, **_kwargs):
    write_audio(output, 0.3)
    return output


class TestMusicLengthIsTheFilmLength:
    def test_a_known_film_length_is_the_plan_not_the_per_clip_floor(self) -> None:
        timeline = _photo_film(30, film_seconds=100.0)

        assert timeline.music_duration == pytest.approx(100.0, abs=1.5)
        assert sum(scene["duration"] for scene in timeline.build_scenes()) == pytest.approx(
            100.0, abs=1.5
        )

    def test_without_a_film_length_short_clips_are_not_floored_to_five_seconds(self) -> None:
        timeline = _photo_film(30, film_seconds=None)

        # 30 photos of 3.5 s, the title, the ending and the fade buffer: not 30 x 5 s.
        expected = 3.5 + 30 * PHOTO_SECONDS + 4.0 + timeline.fade_buffer
        assert timeline.music_duration == pytest.approx(expected, abs=1.0)
        assert sum(scene["duration"] for scene in timeline.build_scenes()) == pytest.approx(
            expected, abs=1.0
        )

    async def test_a_short_photo_film_is_one_take(self, tmp_path: Path) -> None:
        gen = RecordingGenerator(max_take=300)
        pipeline = MusicPipeline(generators=[gen], block_seconds=120, max_blocks=3)

        async with pipeline:
            result = await pipeline.generate_music_for_video(
                timeline=_photo_film(30, film_seconds=100.0), output_dir=tmp_path, num_versions=1
            )

        assert len(gen.requests) == 1, "a 100 s film never takes the block path"
        assert gen.requests[0].duration_seconds == pytest.approx(100, abs=2)
        assert result.versions[0].duration == pytest.approx(100.0, abs=1.5)

    def test_auto_generation_plans_from_the_assembled_film(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from immich_memories.config_loader import Config
        from immich_memories.generate_music import resolve_music
        from immich_memories.processing.assembly_config import AssemblyClip

        seen: list[VideoTimeline] = []

        async def capture(*, timeline, **_kwargs):
            seen.append(timeline)
            raise RuntimeError("stop after planning")

        # WHY: the generator service is the external boundary; the plan is what we check.
        monkeypatch.setattr(
            "immich_memories.audio.music_generator.generate_music_for_video", capture
        )
        config = Config()
        config.ace_step.enabled = True
        clips = [
            AssemblyClip(tmp_path / f"p{i}.mp4", PHOTO_SECONDS, is_photo=True) for i in range(30)
        ]
        resolve_music(
            config,
            None,
            False,
            clips,
            tmp_path,
            None,
            transition_overlap=0.5,
            video_duration=97.0,
        )

        assert seen, "generation was attempted"
        assert seen[0].film_duration == 97.0


class TestMusicGenGetsChapters:
    def test_one_mood_with_no_dividers_is_one_scene_not_one_per_clip(self) -> None:
        scenes = _photo_film(30, film_seconds=100.0).build_scenes()

        assert len(scenes) == 1

    def test_a_long_chapter_is_split_into_service_sized_scenes(self) -> None:
        scenes = _photo_film(80, film_seconds=260.0).build_scenes()

        assert all(5 <= scene["duration"] <= 120 for scene in scenes)
        assert len({scene["mood"] for scene in scenes}) == 1
        assert sum(scene["duration"] for scene in scenes) == pytest.approx(260.0, abs=1.5)

    def test_month_chapters_each_get_one_scene(self) -> None:
        clips = [ClipMood(duration=4.0, mood="happy", month=6) for _ in range(10)]
        clips += [ClipMood(duration=4.0, mood="happy", month=7) for _ in range(10)]
        clips[9].has_transition_after = True
        timeline = VideoTimeline(clips=clips, film_duration=90.0)

        scenes = timeline.build_scenes()

        assert len(scenes) == 2

    def test_a_clip_whose_mood_flickers_joins_its_chapter(self) -> None:
        moods = ["happy", "calm"] * 15
        timeline = VideoTimeline(
            clips=[ClipMood(duration=PHOTO_SECONDS, mood=mood) for mood in moods],
            film_duration=110.0,
        )

        scenes = timeline.build_scenes()

        assert all(scene["duration"] >= 20 for scene in scenes), scenes


def _identity(take: dict[str, Any]) -> tuple:
    return (take["caption"], take["bpm"], take["keyscale"], take["timesignature"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["lib", "api"])
async def test_every_block_of_one_film_shares_caption_style_bpm_and_key(
    mode,
    tmp_path,
    monkeypatch,
    ace_boundary,  # noqa: F811 - pytest fixture
):
    backend, captured = ace_boundary(mode)
    styles = iter(sorted(ace_step_captions.STYLE_PROFILES) * 4)
    # WHY: a fresh process per block used to draw its own style; make every unpinned
    # draw differ so a film-wide pin is the only way the blocks can agree.
    monkeypatch.setattr(ace_step_captions.random, "choice", lambda _pool: next(styles))
    monkeypatch.setattr(
        "immich_memories.audio.music_pipeline.join_takes", _fake_join, raising=False
    )
    pipeline = MusicPipeline(generators=[backend], block_seconds=75, max_blocks=3)

    async with pipeline:
        await pipeline.generate_music_for_video(
            timeline=_photo_film(50, film_seconds=183.0),
            output_dir=tmp_path,
            num_versions=1,
        )

    assert len(captured) == 3
    assert len({_identity(take) for take in captured}) == 1, captured
    assert captured[0]["keyscale"], "the key is pinned, not left to each take"
    film_seeds = {request.seed for request in backend.requests}
    assert None not in film_seeds and len(film_seeds) == 1, "one seed lineage per film"
    base = film_seeds.pop()
    assert [take["seed"] for take in captured] == [base, base + 1, base + 2]


def test_the_isolated_child_receives_the_films_seed(tmp_path: Path) -> None:
    from immich_memories.audio.generators.ace_step_isolated import request_from_payload

    request = GenerationRequest(scenes=[{"mood": "happy", "duration": 183}], output_dir=tmp_path)
    request.seed = 1234
    restored = request_from_payload(json.loads(json.dumps(asdict(request), default=str)))

    assert restored.seed == 1234


def test_one_seed_pins_the_caption_even_without_a_genre() -> None:
    from immich_memories.audio.generators.ace_step_captions import build_ace_caption_structured

    captions = {
        build_ace_caption_structured("happy", memory_type="trip", rng=random.Random(7)).caption
        for _ in range(5)
    }

    assert len(captions) == 1


def test_metal_is_never_a_random_pick() -> None:
    picks = {ace_step_captions.pick_style(rng=random.Random(seed)) for seed in range(400)}

    assert "metal" not in picks
    assert ace_step_captions.pick_style(genres=["metal"]) == "metal"


class TestOneBackendPerFilm:
    async def test_blocks_come_from_one_backend_and_are_joined_on_bars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = RecordingGenerator("ACE", max_take=300)
        second = RecordingGenerator("MusicGen")
        joined: list[dict[str, Any]] = []

        def join(blocks, target, output, **kwargs):
            joined.append({"blocks": list(blocks), "target": target, **kwargs})
            return _fake_join(blocks, target, output)

        # WHY: the FFmpeg join has its own integration test; this checks what it is given.
        monkeypatch.setattr("immich_memories.audio.music_pipeline.join_takes", join, raising=False)
        pipeline = MusicPipeline(generators=[first, second], block_seconds=120, max_blocks=3)

        async with pipeline:
            await pipeline.generate_music_for_video(
                timeline=_photo_film(80, film_seconds=300.0), output_dir=tmp_path, num_versions=1
            )

        assert len(first.requests) == 3
        assert second.requests == []
        assert joined and joined[0]["bpm"] == 96
        assert joined[0]["target"] == pytest.approx(300.0, abs=1.5)

    async def test_a_backend_that_covers_any_length_gets_the_whole_film_at_once(
        self, tmp_path: Path
    ) -> None:
        musicgen = RecordingGenerator("MusicGen", max_take=None)
        pipeline = MusicPipeline(generators=[musicgen], block_seconds=120, max_blocks=3)

        async with pipeline:
            await pipeline.generate_music_for_video(
                timeline=_photo_film(80, film_seconds=300.0), output_dir=tmp_path, num_versions=1
            )

        assert len(musicgen.requests) == 1
        scenes = musicgen.requests[0].scenes
        assert sum(scene["duration"] for scene in scenes) == pytest.approx(300.0, abs=1.5)
        assert len(scenes) <= 3

    async def test_a_failed_first_backend_hands_the_whole_film_to_the_next(
        self, tmp_path: Path
    ) -> None:
        broken = RecordingGenerator("ACE", max_take=300, fail=True)
        musicgen = RecordingGenerator("MusicGen")
        pipeline = MusicPipeline(generators=[broken, musicgen], block_seconds=120, max_blocks=3)

        async with pipeline:
            result = await pipeline.generate_music_for_video(
                timeline=_photo_film(80, film_seconds=300.0), output_dir=tmp_path, num_versions=1
            )

        assert len(musicgen.requests) == 1
        assert len(result.versions) == 1
