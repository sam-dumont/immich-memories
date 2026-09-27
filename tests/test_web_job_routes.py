"""The browser starts the real commands; these checks watch what it asks the CLI to run."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

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
    started = client.post(f"/api/v1/runs/{RUN}/renders", json={"revision": 2, "music": "none"})

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
        llm_title=False,
    )

    emitted = {flag.split("=")[0] for flag in everything.flags(Path("/music/track.mp3"))}

    assert emitted <= accepted, emitted - accepted


def test_who_names_the_film_is_left_to_generate_unless_the_owner_says():
    from immich_memories.web.job_routes import RenderOptions

    def naming(choice):
        return [f for f in RenderOptions(llm_title=choice).flags() if "llm-title" in f]

    assert naming(None) == []
    assert naming(True) == ["--llm-title"]
    assert naming(False) == ["--no-llm-title"]


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
            return [
                SimpleNamespace(id="a", name="Trip", asset_count=40),
                SimpleNamespace(id="b", name="Trip", asset_count=300),
            ]

    client = api_client(config_in(tmp_path))
    # WHY: Immich is the external boundary; the unit tier has no library to read.
    client.app.dependency_overrides[immich_client] = lambda: Library()

    assert [p["name"] for p in client.get("/api/v1/people").json()] == ["Ana", "zoé"]
    # Largest first, each with its id: two albums may share a name, and --from-album takes either.
    assert [(a["id"], a["asset_count"]) for a in client.get("/api/v1/albums").json()] == [
        ("b", 300),
        ("a", 40),
    ]


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


def test_music_is_previewed_by_music_preview_uploaded_and_played_back(client):
    started = client.post(f"/api/v1/runs/{RUN}/music-preview")
    job = _finished(client, started.json()["id"])
    argv = json.loads(client.recorded.read_text())
    assert job["status"] == "succeeded" and argv[argv.index("music") + 1] == "preview"
    assert "--progress-file" in argv and job["command"] == f"immich-memories music preview {RUN}"

    uploaded = client.post("/api/v1/music", files={"file": ("song.mp3", b"ID3tune", "audio/mpeg")})
    refused = client.post("/api/v1/music", files={"file": ("notes.txt", b"hi", "text/plain")})
    played = client.get(f"/api/v1/music/{uploaded.json()['id']}")

    assert uploaded.status_code == 201 and played.content == b"ID3tune"
    assert refused.status_code == 422
    assert client.get("/api/v1/music/..%2F..%2Fsecret").status_code == 404

    render = client.post(f"/api/v1/runs/{RUN}/renders", json={"music": uploaded.json()["id"]})
    _finished(client, render.json()["id"])
    argv = json.loads(client.recorded.read_text())
    assert any(flag.startswith("--music=") and flag.endswith(".mp3") for flag in argv)


def test_a_cut_s_progress_carries_the_stage_s_own_time_left(client, tmp_path):
    from immich_memories.operations.cut_progress import StageUpdate
    from immich_memories.operations.editorial_attempt import EditorialAttempt

    started = client.post("/api/v1/cuts", json={"memory_type": "year_in_review", "year": 2023})
    job_id = started.json()["id"]
    root = tmp_path / "cache" / "editorial-runs" / f"web-{job_id}"
    with EditorialAttempt(root, request={"key": "k"}) as attempt:
        # The estimate is measured from this stage's own work, so it needs two samples.
        attempt.stage(StageUpdate("previews", done=30, total=120))
        time.sleep(0.2)
        attempt.stage(StageUpdate("previews", done=60, total=120))
        progress = client.get(f"/api/v1/jobs/{job_id}").json()["progress"]

    assert (progress["done"], progress["total"], progress["fraction"]) == (60, 120, 0.5)
    # 30 pictures took ~0.2 s, so the 60 left are ~0.4 s away.
    assert 0.2 < progress["remaining_seconds"] < 5


def test_a_stage_that_counts_nothing_offers_no_time_left(client, tmp_path):
    from immich_memories.operations.cut_progress import StageUpdate
    from immich_memories.operations.editorial_attempt import EditorialAttempt

    started = client.post("/api/v1/cuts", json={"memory_type": "year_in_review", "year": 2023})
    job_id = started.json()["id"]
    root = tmp_path / "cache" / "editorial-runs" / f"web-{job_id}"
    with EditorialAttempt(root, request={"key": "k"}) as attempt:
        attempt.stage(StageUpdate("Reading the period account", remaining_seconds=9.0))
        progress = client.get(f"/api/v1/jobs/{job_id}").json()["progress"]

    assert progress["remaining_seconds"] is None
