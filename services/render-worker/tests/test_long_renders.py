"""The worker gives a long film the deadline its work needs."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from test_app_handoff import manual_params

from conftest import render_request_body


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


def test_the_worker_gives_a_long_film_more_than_its_configured_deadline(tmp_path):
    """The worker's deadline grows with the film, as the app's wait does."""
    from immich_memories_render_worker.jobs import RenderJobs
    from immich_memories_render_worker.models import RenderRequest
    from immich_memories_render_worker.settings import WorkerSettings

    from immich_memories.processing.remote_render_plan import build_render_request

    class Renderer:
        def health(self):
            return {"ready": True}

        def render(self, request, directory, progress):
            raise AssertionError("the deadline is checked on a job that is not rendering")

    service = RenderJobs(
        WorkerSettings(
            token="long-film-test-worker-token-7c41e9a0b2d8",  # noqa: S106
            immich_url="http://immich.invalid",
            directory=tmp_path / "worker",
            job_timeout_seconds=3600,
        ),
        Renderer(),
    )
    try:
        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        statuses = {}
        for name, body in {
            "long": build_render_request(long_film_params(tmp_path)),
            "short": render_request_body(memory_key="short-cut"),
        }.items():
            job_id = uuid4()
            statuses[name] = job_id
            request = RenderRequest.model_validate(body)
            # WHY: admission as `submit` records it, without starting the single render lane.
            service.store.admit(service.job_status(job_id, request), name)
            service.store.update(job_id, state="running", started_at=two_hours_ago)
        service.cleanup()
        assert service.store.get(statuses["long"]).state == "running"
        assert service.store.get(statuses["short"]).state == "failed"
        assert "3600s" in service.store.get(statuses["short"]).error
    finally:
        service.close()
