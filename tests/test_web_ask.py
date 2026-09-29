"""A film from a sentence in the browser: the dry run as a preview, then the same cut as the CLI."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from immich_memories.config_loader import Config
from immich_memories.web.job_routes import cli_executable
from tests.web_api_fixtures import api_client, config_in


def _full_tier(tmp_path: Path) -> Config:
    config = Config.model_validate(
        {"tier": "full", "llm": {"base_url": "http://reader.invalid/v1", "model": "small-reader"}}
    )
    config.cache = config_in(tmp_path).cache
    return config


def test_the_sentence_box_is_there_on_the_model_tier_only(tmp_path):
    reduced = config_in(tmp_path)

    assert api_client(_full_tier(tmp_path)).get("/api/v1/ask").json()["available"] is True
    answer = api_client(reduced).get("/api/v1/ask").json()
    assert answer == {"available": False, "tier": reduced.tier}


TRANSLATION = {
    "request": "our cat along the years",
    "blocks": [{"head": "VERDICT", "lines": ["possible: 14 pictures"]}],
    "pool": {"pictures": 14, "photos": 14, "videos": 0},
    "verdict": "possible",
    "why": "14 pictures",
    "film": {"route": "pool", "line": "the engine films the pool", "outcome": "14 pictures"},
}


def _dry_run_cli(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in `immich-memories` that keeps its argv and writes the translation it is asked for."""
    recorder = tmp_path / "argv.json"
    fake = tmp_path / "immich-memories"
    fake.write_text(
        f"#!{sys.executable}\nimport json, pathlib, sys\nargs = sys.argv[1:]\n"
        f"open({str(recorder)!r}, 'w').write(json.dumps(args))\n"
        "if '--ask-trace' in args:\n"
        "    kept = pathlib.Path(args[args.index('--ask-trace') + 1])\n"
        "    kept.parent.mkdir(parents=True, exist_ok=True)\n"
        f"    kept.write_text({json.dumps(TRANSLATION)!r})\n"
    )
    fake.chmod(0o755)
    return fake, recorder


def _finished(client, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    pytest.fail("job never finished")


def test_a_preview_is_the_dry_run_and_reads_back_the_translation_it_kept(tmp_path):
    fake, recorder = _dry_run_cli(tmp_path)
    client = api_client(_full_tier(tmp_path))
    # WHY: the real CLI child reads the store and asks the model; this checks what the web runs.
    client.app.dependency_overrides[cli_executable] = lambda: str(fake)

    started = client.post("/api/v1/ask/preview", json={"sentence": "our cat along the years"})

    assert started.status_code == 202
    job = _finished(client, started.json()["id"])
    argv = json.loads(recorder.read_text())
    assert job["status"] == "succeeded" and job["kind"] == "ask"
    assert "--ask=our cat along the years" in argv and "--dry-run" in argv
    assert job["command"] == "immich-memories generate '--ask=our cat along the years' --dry-run"
    assert client.get(f"/api/v1/ask/preview/{job['id']}").json() == TRANSLATION


def test_off_the_model_tier_a_preview_is_refused_and_no_job_starts(tmp_path):
    client = api_client(config_in(tmp_path))

    refused = client.post("/api/v1/ask/preview", json={"sentence": "our cat along the years"})

    assert refused.status_code == 422
    assert "model tier" in refused.json()["detail"]
    assert client.get("/api/v1/jobs/active").json() is None


def test_making_the_film_is_the_ordinary_cut_of_the_same_sentence(tmp_path):
    fake, recorder = _dry_run_cli(tmp_path)
    client = api_client(_full_tier(tmp_path))
    # WHY: the real CLI child reads Immich and cuts; this checks the command the web runs.
    client.app.dependency_overrides[cli_executable] = lambda: str(fake)

    started = client.post("/api/v1/cuts", json={"ask": "our cat along the years"})

    job = _finished(client, started.json()["id"])
    argv = json.loads(recorder.read_text())
    assert job["kind"] == "cut"
    assert "--ask=our cat along the years" in argv and "--no-render" in argv
    assert "--dry-run" not in argv
