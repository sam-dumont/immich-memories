"""A long film gets the wait its work needs, and a render that stops moving still fails."""

from uuid import uuid4

import pytest

WORKER_TOKEN = "waits-test-worker-token-5d0c81f2a7e3"  # noqa: S105


def manual_params(tmp_path):
    """One ten-second video, cut to 3.25 s, as a manual film hands it to the worker."""
    from immich_memories.api.models import Asset, VideoClipInfo
    from immich_memories.config import Config
    from immich_memories.generate import GenerationParams

    asset = Asset(
        id=str(uuid4()),
        type="VIDEO",
        originalFileName="source.mp4",
        fileCreatedAt="2026-01-01T12:00:00Z",
        fileModifiedAt="2026-01-01T12:00:00Z",
        updatedAt="2026-01-01T12:00:00Z",
        duration="00:00:10",
    )
    config = Config()
    config.immich.url = "http://immich.invalid"
    config.immich.api_key = "test-scoped-key"
    config.title_screens.enabled = False
    return GenerationParams(
        clips=[VideoClipInfo(asset=asset, duration_seconds=10, width=1920, height=1080)],
        output_path=tmp_path / "film.mp4",
        config=config,
        target_duration_seconds=30,
        clip_segments={asset.id: (2.5, 5.75)},
        memory_key_override="manual-cut",
    )


def long_film_params(tmp_path, *, clips: int = 155, seconds: float = 4.0):
    """A cut the size of a ten-minute film: 155 four-second clips."""
    from immich_memories.api.models import VideoClipInfo

    params = manual_params(tmp_path)
    template = params.clips[0]
    params.clips, params.clip_segments = [], {}
    for _ in range(clips):
        asset = template.asset.model_copy(update={"id": str(uuid4())})
        params.clips.append(
            VideoClipInfo(asset=asset, duration_seconds=10, width=1920, height=1080)
        )
        params.clip_segments[asset.id] = (0.0, seconds)
    params.target_duration_seconds = clips * seconds
    return params


class _Clock:
    """Worker time: each poll of the job is one minute of rendering."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, _seconds):
        self.now += 60


def _render(tmp_path, monkeypatch, params, state_at):
    """Run the app's client against a worker whose job reports ``state_at(minute)``."""
    import json

    import httpx

    from immich_memories import __version__
    from immich_memories.config.models.render import RenderWorkerConfig
    from immich_memories.generate import GenerationError
    from immich_memories.processing import remote_render
    from immich_memories.processing.remote_render import RemoteRenderClient

    clock = _Clock()
    # WHY: hours of worker time in milliseconds; the clock is the boundary replaced.
    monkeypatch.setattr(remote_render, "time", clock)
    settings = RenderWorkerConfig(
        worker_base_url="https://worker.example.com", worker_token=WORKER_TOKEN
    )
    body, job_id = {}, str(uuid4())

    def respond(request):
        if request.url.path == "/health":
            return httpx.Response(
                200, json={"app_version": __version__, "contract_version": 2, "ready": True}
            )
        if request.method == "POST":
            body.update(json.loads(request.content))
        status = {"job_id": job_id, "memory_key": body["memory_key"]}
        status |= {"plan_digest": body["timing"]["sha256"]}
        return httpx.Response(200, json=status | state_at(int(clock.now // 60)))

    # WHY: the worker's HTTP API without a worker; the request is the app's real one.
    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as http,
        pytest.raises(GenerationError) as error,
    ):
        RemoteRenderClient(settings, client=http).render(
            params, tmp_path / "film.mp4", lambda *_: None
        )
    return str(error.value), clock.now


def _encoding(minute):
    return {"state": "running", "phase": "assembly", "message": f"Encoding, minute {minute}"}


def test_a_ten_minute_film_is_still_awaited_after_the_configured_hour(tmp_path, monkeypatch):
    """Queued for 40 minutes, then two more hours of progress: the worker's own answer wins."""

    def state_at(minute):
        if minute < 40:
            return {"state": "queued"}
        if minute < 160:
            return _encoding(minute)
        return {"state": "failed", "error": "the encoder stopped at the last clip"}

    message, waited = _render(tmp_path, monkeypatch, long_film_params(tmp_path), state_at)
    assert "the encoder stopped at the last clip" in message
    assert waited > 2 * 3600


def test_a_short_film_keeps_the_configured_hour(tmp_path, monkeypatch):
    message, waited = _render(tmp_path, monkeypatch, manual_params(tmp_path), _encoding)
    assert message == "Render worker timed out"
    assert 3600 <= waited < 3600 + 120


def test_a_running_render_that_stops_moving_fails_long_before_its_budget(tmp_path, monkeypatch):
    def state_at(minute):
        return _encoding(min(minute, 30))

    message, waited = _render(tmp_path, monkeypatch, long_film_params(tmp_path), state_at)
    assert "made no progress for 20 minutes" in message
    assert 30 * 60 + 20 * 60 <= waited < 30 * 60 + 22 * 60


def test_a_special_days_dates_come_back_from_the_cut_it_kept(tmp_path):
    """The saved cut keeps a special day's day, window and run as dates and instants."""
    from datetime import UTC, date, datetime

    from immich_memories.processing.render_inputs import read_cut_titles, write_cut_titles

    params = {
        "day": date(2024, 2, 7),
        "window": (datetime(2024, 2, 7, 9, 30), datetime(2024, 2, 7, 17, 0)),
        "run": [datetime(2024, 2, 7, 8, 0, tzinfo=UTC), datetime(2024, 2, 8, 1, 15, tzinfo=UTC)],
        "title": "",
    }
    write_cut_titles(tmp_path, title=None, subtitle=None, source=None, preset_params=params)
    kept = read_cut_titles(tmp_path)
    assert kept is not None
    assert kept.preset_params == params | {"window": list(params["window"])}
