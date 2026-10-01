"""A pipeline take's bound reaches ACE-Step without discarding the film's moods."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from immich_memories.audio.generators.ace_step_backend import ACEStepBackend, ACEStepConfig
from immich_memories.audio.generators.ace_step_runtime import ACEStepV15Runtime
from immich_memories.audio.generators.base import GenerationRequest
from immich_memories.audio.music_pipeline import MusicPipeline
from tests.generated_audio_fixtures import write_audio


class ReadyACE(ACEStepBackend):
    """Use real request translation with a synthetic external inference boundary."""

    async def is_available(self):
        return True

    async def generate(self, request, progress_callback=None):
        self.requests.append(request)
        if self.config.mode == "lib":
            result = await self._generate_lib(request, progress_callback)
        else:
            result = await self._generate_api(request, progress_callback)
        self.results.append(result)
        return result


@pytest.fixture
def ace_boundary(tmp_path, monkeypatch):
    captured = []
    waveform = tmp_path / "upstream.wav"
    write_audio(waveform, 0.5)

    def local_generate(*, params, save_dir, **_kwargs):
        captured.append({"duration": params.duration, "caption": params.caption})
        return SimpleNamespace(success=True, audios=[{"path": str(waveform)}])

    def remote(request):
        if request.url.path == "/release_task":
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"data": {"task_id": "take"}})
        if request.url.path == "/query_result":
            return httpx.Response(
                200,
                json={"data": [{"status": 1, "result": '[{"file":"/track.wav"}]'}]},
            )
        assert request.url.path == "/track.wav"
        return httpx.Response(200, content=waveform.read_bytes())

    original_client = httpx.AsyncClient
    # WHY: the hosted ACE service is external; retain real HTTP serialization/poll/download.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(remote), **kwargs),
    )

    def create(mode):
        backend = ReadyACE(ACEStepConfig(mode=mode, api_url="http://ace.test"))
        backend.requests = []
        backend.results = []
        # WHY: native ACE weights are the external inference boundary; test real params.
        backend._pipeline = ACEStepV15Runtime(
            dit_handler=None,
            llm_handler=None,
            generation_params_type=SimpleNamespace,
            generation_config_type=SimpleNamespace,
            generate_music=local_generate,
            device="cpu",
            lm_backend="pt",
            dit_model="acestep-v15-turbo",
            lm_model=None,
        )
        return backend, captured

    return create


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["lib", "api"])
async def test_pipeline_block_bound_reaches_native_ace_params(
    mode, tmp_path, monkeypatch, ace_boundary
):
    backend, captured = ace_boundary(mode)
    pipeline = MusicPipeline(generators=[backend], block_seconds=75, max_blocks=3)
    scenes = [{"mood": "happy", "duration": 100}, {"mood": "calm", "duration": 83}]

    def assemble(_blocks, _duration, output, **_kwargs):
        write_audio(output, 0.5)

    # WHY: block assembly is a separate FFmpeg concern; native parameter translation is real.
    monkeypatch.setattr("immich_memories.audio.music_pipeline.assemble_music", assemble)
    result = await pipeline._generate_full_mix(
        scenes=scenes,
        primary_mood="happy",
        total_duration=183,
        output_dir=tmp_path,
        crossfade_duration=2.0,
        memory_type="trip",
        photo_cadence_seconds=None,
        mood_detail=None,
        candidate_index=0,
        num_versions=1,
        progress_callback=None,
    )

    assert result is not None
    assert len(captured) == 3
    assert [take["duration"] for take in captured] == [75, 75, 75]
    assert all(take["caption"] for take in captured)
    assert all(request.scenes == scenes for request in backend.requests)
    assert [result.duration_seconds for result in backend.results] == [75, 75, 75]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["lib", "api"])
@pytest.mark.parametrize(
    ("scenes", "duration", "limit", "expected"),
    [
        ([{"mood": "happy", "duration": 20}, {"mood": "calm", "duration": 15}], 60, None, 35),
        ([{"mood": "happy", "duration": 400}, {"mood": "calm", "duration": 200}], 60, 500, 300),
        ([], 32, 75, 32),
    ],
)
async def test_legacy_scene_length_and_backend_cap_survive_take_limit(
    mode, scenes, duration, limit, expected, tmp_path, ace_boundary
):
    backend, captured = ace_boundary(mode)
    result = await backend.generate(
        GenerationRequest(
            prompt="happy",
            scenes=scenes,
            duration_seconds=duration,
            duration_limit_seconds=limit,
            output_dir=tmp_path,
        )
    )
    assert captured[0]["duration"] == expected
    assert result.duration_seconds == expected


def test_isolated_child_receives_the_take_limit_and_full_scene_context(tmp_path):
    from dataclasses import asdict

    from immich_memories.audio.generators.ace_step_isolated import request_from_payload

    request = GenerationRequest(
        scenes=[{"mood": "happy", "duration": 183}],
        duration_seconds=75,
        duration_limit_seconds=75,
        output_dir=tmp_path,
    )
    restored = request_from_payload(json.loads(json.dumps(asdict(request), default=str)))
    assert restored.duration_limit_seconds == 75
    assert restored.scenes == request.scenes
