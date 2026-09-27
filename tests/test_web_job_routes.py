"""The browser starts the real commands; these checks watch what it asks the CLI to run."""

from __future__ import annotations

import json
import sys
import time

import pytest

from immich_memories.web.job_routes import cli_executable
from tests.web_api_fixtures import api_client, config_in, save_run

RUN = "20260927_090000_beef"


@pytest.fixture
def client(tmp_path):
    config = config_in(tmp_path)
    save_run(config, RUN)
    recorder = tmp_path / "argv.json"
    fake = tmp_path / "immich-memories"
    fake.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"open({str(recorder)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
    )
    fake.chmod(0o755)
    client = api_client(config)
    # WHY: the real CLI child needs Immich; these checks are about the command the web runs.
    client.app.dependency_overrides[cli_executable] = lambda: str(fake)
    client.recorded = recorder
    return client


def _finished(client, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    pytest.fail("job never finished")


def test_a_cut_runs_generate_no_render_and_shows_the_command_a_person_would_type(client):
    started = client.post(
        "/api/v1/cuts", json={"memory_type": "monthly_highlights", "year": 2024, "month": 6}
    )

    assert started.status_code == 202
    job = _finished(client, started.json()["id"])
    argv = json.loads(client.recorded.read_text())
    assert job["status"] == "succeeded"
    assert argv[0] == "generate" or argv[2] == "generate"
    assert "--memory-type=monthly_highlights" in argv and "--no-render" in argv
    assert job["command"] == (
        "immich-memories generate --memory-type=monthly_highlights --year=2024 --month=6 --no-render"
    )


def test_a_render_runs_runs_render_with_its_revision_and_a_progress_file(client):
    started = client.post(f"/api/v1/runs/{RUN}/renders", json={"revision": 2, "no_music": True})

    job = _finished(client, started.json()["id"])
    argv = json.loads(client.recorded.read_text())
    assert job["status"] == "succeeded"
    assert argv[argv.index("runs") : argv.index("runs") + 3] == ["runs", "render", RUN]
    assert "--revision=2" in argv and "--no-music" in argv and "--progress-file" in argv
    assert job["command"] == f"immich-memories runs render {RUN} --revision=2 --no-music"
    assert client.post("/api/v1/runs/never/renders", json={}).status_code == 404


def test_every_render_flag_the_web_can_send_is_one_runs_render_accepts():
    from immich_memories.cli import main
    from immich_memories.web.job_routes import RenderOptions

    render = main.commands["runs"].commands["render"]
    accepted = {name for param in render.params for name in (*param.opts, *param.secondary_opts)}
    everything = RenderOptions(
        revision=1,
        title="t",
        subtitle="s",
        transition="cut",
        resolution="1080p",
        orientation="auto",
        format="mp4",
        no_music=True,
        music_volume=0.4,
        add_date=True,
        add_place=True,
        privacy_mode=True,
        upload_to_immich=True,
        album="a",
    )

    emitted = {flag.split("=")[0] for flag in everything.flags()}

    assert emitted <= accepted, emitted - accepted


def test_the_brief_picks_from_the_library_s_named_people_and_albums(tmp_path):
    from types import SimpleNamespace

    from immich_memories.web.library import immich_client

    class Library:
        def get_all_people(self):
            return [
                SimpleNamespace(id="2", name="zoé"),
                SimpleNamespace(id="1", name="Ana"),
                SimpleNamespace(id="3", name=""),
            ]

        def list_albums(self):
            return [SimpleNamespace(id="a", name="Trip", asset_count=40)]

    client = api_client(config_in(tmp_path))
    # WHY: Immich is the external boundary; the unit tier has no library to read.
    client.app.dependency_overrides[immich_client] = lambda: Library()

    assert [p["name"] for p in client.get("/api/v1/people").json()] == ["Ana", "zoé"]
    assert client.get("/api/v1/albums").json() == [{"id": "a", "name": "Trip", "asset_count": 40}]


def test_the_page_shows_the_command_its_brief_stands_for_before_running_it(client):
    shown = client.post(
        "/api/v1/cuts/command", json={"memory_type": "year_in_review", "year": 2023}
    )

    assert shown.json() == {
        "command": "immich-memories generate --memory-type=year_in_review --year=2023 --no-render"
    }


def test_cut_again_from_a_terminal_made_run_keeps_its_scope_and_adds_the_ticks(client):
    started = client.post(
        f"/api/v1/runs/{RUN}/recut", json={"include": ["garden-2"], "exclude": ["lake-1"]}
    )

    job = _finished(client, started.json()["id"])
    argv = json.loads(client.recorded.read_text())
    assert job["status"] == "succeeded"
    assert "--memory-type=monthly_highlights" in argv
    assert "--include=garden-2" in argv and "--exclude=lake-1" in argv


def test_rescanning_people_runs_people_scan(client):
    started = client.post("/api/v1/roster/scan")

    job = _finished(client, started.json()["id"])
    argv = json.loads(client.recorded.read_text())
    assert job["status"] == "succeeded" and argv[-2:] == ["people", "scan"]
    assert job["command"] == "immich-memories people scan"
