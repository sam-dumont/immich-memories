"""The browser shows a terminal job error even when no output log is available."""

import json
import time

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_full_storage_ends_progress_and_shows_recovery_without_a_log(page, launch_app_url):
    job = {
        "id": "a" * 32,
        "kind": "cut",
        "argv": [],
        "status": "running",
        "started_at": time.time(),
        "command": "immich-memories generate --no-render",
        "progress": {"label": "Preparing the pool", "recent_asset_ids": []},
    }
    message = "Storage is full. Expand the cache volume, then retry."
    failed = {**job, "status": "failed", "exit_code": 1, "error": message}
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # WHY: the API boundary supplies a failed job whose disk could not retain its log.
    page.route("**/api/v1/jobs/active", lambda route: route.fulfill(json=job))
    page.route(
        f"**/api/v1/jobs/{job['id']}/events",
        lambda route: route.fulfill(
            body=f"data: {json.dumps(failed)}\n\n", content_type="text/event-stream"
        ),
    )
    page.route(f"**/api/v1/jobs/{job['id']}/output", lambda route: route.abort())
    page.goto(f"{launch_app_url}/app/create")

    panel = page.get_by_role("region", name="Progress")
    expect(panel.get_by_text("It did not finish.")).to_be_visible()
    expect(panel.get_by_role("alert")).to_have_text(message)
    expect(panel.get_by_role("progressbar")).to_have_count(0)
    expect(panel.get_by_role("button", name="Cancel")).to_have_count(0)
    assert errors == []


def _running_job():
    return {
        "id": "b" * 32,
        "kind": "cut",
        "argv": [],
        "status": "running",
        "started_at": time.time(),
        "command": "immich-memories generate --no-render",
        "progress": {
            "label": "Preparing videos.detector_frames: 1/1",
            "stage_name": "videos.detector_frames",
            "fraction": 1.0,
            "fraction_scope": "stage",
            "stage_fraction": 1.0,
            "done": 1,
            "total": 1,
            "unit": "clips",
            "pass_id": 1,
            "updated_at": time.time(),
            "recent_asset_ids": [],
        },
    }


def test_finished_sampling_moves_to_live_photo_checks_with_a_fresh_stage_bar(
    page,
    launch_app_url,
    tmp_path,
    monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import httpx

    from immich_memories.operations.cut_progress import StageUpdate
    from immich_memories.operations.editorial_attempt import EditorialAttempt
    from immich_memories.web.job_routes import _view
    from immich_memories.web.schemas import Job
    from tests.test_editorial_preparation import asset
    from tests.test_playback_keyframes import encode
    from tests.test_remote_facts_preparation import answer, remote_run, transport
    from tests.web_api_fixtures import config_in

    config = config_in(tmp_path)
    job = Job.model_validate(_running_job())
    root = config.cache.cache_path / "editorial-runs" / f"web-{job.id}"
    data = encode(tmp_path / "clip.mp4", gop=30)
    waiting, release = Event(), Event()

    def handle(request):
        payload = json.loads(request.content)
        if payload["producers"] == ["nsfw_marqo"]:
            waiting.set()
            assert release.wait(30), "browser did not release the remote frame check"
        return httpx.Response(200, json=answer(payload["producers"]))

    # WHY: only Immich media and inference HTTP are replaced. FFmpeg, preparation,
    # banking, attempt persistence and the job API projection all run for real.
    transport(monkeypatch, handle)

    def prepare():
        with EditorialAttempt(root, request={}) as attempt:
            result = remote_run(
                tmp_path,
                assets=[asset("still").model_copy(update={"live_photo_video_id": "companion"})],
                read_playback=lambda _id, start, length: (data[start : start + length], len(data)),
                progress=lambda label, done, total: attempt.stage(
                    StageUpdate(label, "analysis", done, total)
                ),
            )
            assert result.complete and not result.failures
            attempt.complete(selected=1)

    def saved():
        return _view(config, job).model_dump(mode="json")

    page.route("**/api/v1/jobs/active", lambda route: route.fulfill(json=saved()))
    page.route(f"**/api/v1/jobs/{job.id}", lambda route: route.fulfill(json=saved()))
    page.route(
        f"**/api/v1/jobs/{job.id}/events",
        lambda route: route.fulfill(
            body=f"data: {json.dumps(saved())}\n\n",
            content_type="text/event-stream",
        ),
    )
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(prepare)
        try:
            assert waiting.wait(15), "preparation did not reach frame inference"
            page.goto(f"{launch_app_url}/app/create")
            panel = page.get_by_role("region", name="Progress")
            expect(panel.get_by_text("Checking Live Photo clips", exact=True)).to_be_visible()
            expect(panel.get_by_role("progressbar")).to_have_attribute(
                "aria-valuetext", "0% of this stage"
            )
            expect(panel.get_by_text("0 of 1 clips", exact=True)).to_be_visible()
            expect(panel.get_by_text("Overall time remaining is not known yet.")).to_be_visible()
            panel.get_by_text("Previous stages").click()
            expect(
                panel.get_by_text("Sampling Live Photo frames: 1 of 1 clips", exact=False)
            ).to_be_visible()
            page.reload()
            expect(panel.get_by_text("Checking Live Photo clips", exact=True)).to_be_visible()
        finally:
            release.set()
        future.result(timeout=30)


def test_a_lost_event_stream_recovers_the_terminal_error_from_the_saved_job(page, launch_app_url):
    job = _running_job()
    failed = {**job, "status": "failed", "error": "The render worker stopped.", "exit_code": 1}
    page.route("**/api/v1/jobs/active", lambda route: route.fulfill(json=job))
    page.route(f"**/api/v1/jobs/{job['id']}/events", lambda route: route.abort())
    page.route(f"**/api/v1/jobs/{job['id']}", lambda route: route.fulfill(json=failed))
    page.route(
        f"**/api/v1/jobs/{job['id']}/output", lambda route: route.fulfill(json={"output": ""})
    )
    page.goto(f"{launch_app_url}/app/create")

    panel = page.get_by_role("region", name="Progress")
    expect(panel.get_by_role("alert")).to_have_text("The render worker stopped.")
    expect(panel.get_by_role("progressbar")).to_have_count(0)


def test_a_lost_login_is_visible_without_inventing_a_job_failure(page, launch_app_url):
    job = _running_job()
    page.route("**/api/v1/jobs/active", lambda route: route.fulfill(json=job))
    page.route(f"**/api/v1/jobs/{job['id']}/events", lambda route: route.abort())
    page.route(
        f"**/api/v1/jobs/{job['id']}",
        lambda route: route.fulfill(status=401, json={"detail": "Unauthorized"}),
    )
    page.goto(f"{launch_app_url}/app/create")

    panel = page.get_by_role("region", name="Progress")
    expect(
        panel.get_by_text("Your login expired. Sign in again to see the job’s status.")
    ).to_be_visible()
    expect(panel.get_by_text("It did not finish.")).to_have_count(0)
    expect(panel.get_by_role("link", name="Sign in")).to_be_visible()


def test_whole_film_eta_and_phase_states_survive_reload(
    page, launch_app_url, launch_workspace, tmp_path
):
    from immich_memories.tracking.phase_forecast import PhaseForecast

    job = _running_job()
    from tests.e2e.test_web_client import _seed

    _seed(launch_workspace)
    job["kind"] = "render"
    job["started_at"] = time.time() - 20
    job["meta"] = {"run_id": "20240630_web_cut"}
    forecast = PhaseForecast(
        {"download": 10, "assembly": 100, "music": None, "check": 20, "upload": None},
        target="film",
        skipped={"music", "upload"},
    )
    forecast.enter("download", now=0)
    forecast.enter("assembly", now=10)
    job["progress"]["forecast"] = forecast.snapshot(now=20)
    job["progress"].update(
        label="Encoding",
        stage_name="assembly",
        stage_fraction=None,
        fraction_scope="unknown",
        done=None,
        total=None,
    )
    # WHY: browser transport boundary; the phase snapshot is produced by the real clock.
    page.route("**/api/v1/jobs/active", lambda route: route.fulfill(json=job))
    page.route(f"**/api/v1/jobs/{job['id']}", lambda route: route.fulfill(json=job))
    page.route(f"**/api/v1/jobs/{job['id']}/events", lambda route: route.abort())
    page.goto(launch_app_url + "/app/runs/20240630_web_cut")
    for width in (1280, 375):
        page.set_viewport_size({"width": width, "height": 850})
        panel = page.get_by_role("region", name="Progress", exact=True)
        expect(panel.get_by_text("About 2 min until the film is ready", exact=True)).to_be_visible()
        phases = panel.get_by_role("list", name="Phases")
        expect(phases.get_by_text("Render film", exact=True)).to_be_visible()
        expect(phases.get_by_text("Check playback", exact=True)).to_be_visible()
        expect(phases.get_by_text("Skipped", exact=True)).to_have_count(2)
        expect(panel.get_by_role("progressbar")).to_have_count(0)
        assert panel.bounding_box()["width"] <= width
        page.reload()
    expect(page.get_by_role("list", name="Phases")).to_be_visible()
    page.get_by_role("region", name="Progress", exact=True).screenshot(
        path=str(tmp_path / "progress-mobile.png")
    )


def test_first_run_extrapolation_is_visible_in_the_overall_summary(page, launch_app_url, tmp_path):
    from immich_memories.operations.cut_progress import StageClock, StageUpdate
    from immich_memories.tracking.timing import collecting

    now = [0.0]
    with collecting(now=lambda: now[0]):
        clock = StageClock()
        clock.measure(StageUpdate("previews", "analysis", 0, 1000))
        now[0] = 30
        update = clock.measure(StageUpdate("previews", "analysis", 100, 1000))
    job = _running_job()
    job["started_at"] = time.time() - 30
    job["progress"].update(
        forecast=update.forecast,
        stage_name="previews",
        done=100,
        total=1000,
        stage_fraction=0.1,
        fraction_scope="stage",
        unit="pictures",
    )
    # WHY: transport boundary only; the real stage clock extrapolates the cold pass above.
    page.route("**/api/v1/jobs/active", lambda route: route.fulfill(json=job))
    page.route(f"**/api/v1/jobs/{job['id']}", lambda route: route.fulfill(json=job))
    page.route(f"**/api/v1/jobs/{job['id']}/events", lambda route: route.abort())
    page.set_viewport_size({"width": 375, "height": 850})
    page.goto(launch_app_url + "/app/create")
    panel = page.get_by_role("region", name="Progress", exact=True)
    expect(panel.get_by_text("About 5 min of estimated work left", exact=True)).to_be_visible()
    expect(
        panel.get_by_role("list", name="Phases").get_by_text(
            "~5 min estimated, plus unmeasured work"
        )
    ).to_be_visible()
    expect(panel.get_by_text("100 of 1000 pictures", exact=True)).to_be_visible()
    page.reload()
    expect(panel.get_by_text("About 5 min of estimated work left", exact=True)).to_be_visible()
    panel.screenshot(path=str(tmp_path / "first-run-estimate.png"))
