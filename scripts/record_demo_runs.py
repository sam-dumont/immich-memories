"""Record one real run of each memory type over the demo library, for the docs to replay.

The screenshots, demos and memory-type pages show what the product does with the fixture
library (`tests/e2e/fixtures/library`). Hand-scripted cuts would show what a test author
expected instead, so each memory type is cut once for real: the production `generate`, on the
Full tier with the operator's own model server, against a real Immich seeded with the
library (`make immich-gate-up` then `tests.integration.features.real_seed`).

Each run leaves its decisions in the attempt folder (`plan.private.json`,
`selection-trace.private.json`, `render-projection.private.json`). They are kept under
`tests/e2e/fixtures/recordings/<memory type>/` with the server's asset ids turned back into
the fixture's, so the hermetic fakes can replay the run without a model; the film goes to
`docs-site/static/demo/films/<memory type>.mp4`.

The model is the one the operator's own config names (`llm` in
`~/.immich-memories/config.yaml`). Its settings are copied into the recording home and never
printed. Nothing else is read from the operator's home: the store, the people graph and the
films live in the recording home.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.e2e.fake_library import BIRTH_DATES, household_people  # noqa: E402
from tests.features.cli_harness import UserHome, basic_config  # noqa: E402

RECORDINGS = ROOT / "tests" / "e2e" / "fixtures" / "recordings"
FILMS = ROOT / "docs-site" / "static" / "demo" / "films"
ATTEMPT_FILES = (
    "plan.private.json",
    "selection-trace.private.json",
    "render-projection.private.json",
)

# One film per memory type, asked for the way a user asks for it.
MEMORY_TYPES: dict[str, list[str]] = {
    # A year defaults to ten minutes; the docs page plays three.
    "year_in_review": ["--memory-type", "year_in_review", "--year", "2025", "--duration", "180"],
    "season": ["--memory-type", "season", "--season", "summer", "--year", "2025"],
    "person_spotlight": ["--memory-type", "person_spotlight", "--person", "Kit", "--year", "2025"],
    "multi_person": [
        "--memory-type", "multi_person", "--person", "Robin", "--person", "Kit", "--year", "2025",
    ],
    "monthly_highlights": ["--memory-type", "monthly_highlights", "--month", "7", "--year", "2025"],
    "on_this_day": ["--memory-type", "on_this_day", "--day", "2026-07-21", "--years-back", "1"],
    "album": ["--memory-type", "album", "--from-album", "The road north"],
    "trip": ["--memory-type", "trip", "--year", "2025", "--trip-index", "1"],
    "holiday": ["--memory-type", "holiday", "--holiday", "07-21", "--year", "2025"],
    "special_day": ["--memory-type", "special_day", "--day", "2025-07-05"],
}  # fmt: skip

_RUN_ID = re.compile(r"\b(\d{8}_\d{6}_[0-9a-f]{4})\b")
# "Opening title from model: 'July 2025 highlights'": the title and who wrote it.
# repr() quotes a title holding an apostrophe with double quotes ("Kit's birthday").
_TITLE = re.compile(
    r"Opening title from (?P<source>[a-z ]+): (?:'(?P<single>[^']*)'|\"(?P<double>[^\"]*)\")"
)


def _operator_llm() -> dict[str, Any]:
    """The `llm` section of the operator's config, for the recording home only."""
    path = Path.home() / ".immich-memories" / "config.yaml"
    llm = (yaml.safe_load(path.read_text()) or {}).get("llm")
    if not isinstance(llm, dict) or not llm.get("enabled", True):
        raise SystemExit(f"{path} names no model server; the Full tier needs one")
    return llm


def _home(root: Path, state: dict[str, Any], llm: dict[str, Any]) -> UserHome:
    home = UserHome(root)
    config = basic_config(state["url"], state["api_key"], home)
    config["tier"] = "full"
    config["llm"] = llm
    config["output"].update(resolution="720p", quality="medium")
    home.write_config(config)
    _models_into(root)
    _birth_dates_into(state)
    _household_into(home, state)
    return home


def _birth_dates_into(state: dict[str, Any]) -> None:
    """The cast's birth dates on the real Immich, as the fixture's own server serves them.

    A gate seeded before the cast had birth dates has none, and a birthday then never
    shows up in the recordings.
    """
    headers = {"x-api-key": state["api_key"]}
    for name, born in BIRTH_DATES.items():
        person = state["person_ids"][f"person-{name.lower()}"]
        response = httpx.put(
            f"{state['url']}/api/people/{person}", json={"birthDate": born}, headers=headers
        )
        response.raise_for_status()


def _household_into(home: UserHome, state: dict[str, Any]) -> None:
    """The household's registry, as its owner keeps it, under the real Immich's person ids."""
    document = home.root / "household-people.yaml"
    people = household_people(lambda name: state["person_ids"][f"person-{name.lower()}"])
    document.write_text(yaml.safe_dump(people))
    imported = home.run("people", "import", "--from", str(document), "--replace")
    if imported.returncode != 0:
        raise SystemExit(f"the household did not import: {imported.output[-400:]}")


def _models_into(root: Path) -> None:
    """The pinned exports `models fetch` puts in a home, cloned from the operator's install.

    A copy, not a link: the recording home never writes into the operator's folder. On APFS
    `cp -c` clones without duplicating the bytes.
    """
    source = Path.home() / ".immich-memories" / "models"
    target = root / ".immich-memories" / "models"
    if target.exists() or not source.is_dir():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-cR", str(source), str(target)], check=True)  # noqa: S603, S607


def _env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    # Model weights stay where the operator's own runs downloaded them.
    env.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    env["HOME"] = str(home)
    return env


# The run's own cache keys (request, evidence, judgment, producer and contract digests):
# hashes that mean nothing outside the run, and that secret scanners read as API keys.
_DIGEST = re.compile(r"[0-9a-f]{32,64}")


def _run_cache_key(key: str, value: Any) -> bool:
    return key.endswith("_key") and isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def _fixture_ids(value: Any, fixture_of: dict[str, str]) -> Any:
    """`value` with every server asset id replaced by the fixture's, run cache keys blanked."""
    if isinstance(value, dict):
        return {
            fixture_of.get(k, k): "" if _run_cache_key(k, v) else _fixture_ids(v, fixture_of)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_fixture_ids(v, fixture_of) for v in value]
    if isinstance(value, str):
        return fixture_of.get(value, value)
    return value


def _attempt_dir(home: Path, since: float) -> Path:
    """The attempt folder the run just wrote its plan into."""
    plans = [
        p
        for p in (home / ".immich-memories").rglob("plan.private.json")
        if p.stat().st_mtime >= since
    ]
    if not plans:
        raise SystemExit("the run wrote no editorial plan")
    return max(plans, key=lambda p: p.stat().st_mtime).parent


def record(name: str, home: UserHome, state: dict[str, Any], log: Path) -> dict[str, Any]:
    started = time.time()
    command = [str(ROOT / ".venv" / "bin" / "immich-memories"), "generate", *MEMORY_TYPES[name]]
    with log.open("w") as out:
        result = subprocess.run(  # noqa: S603
            command,
            cwd=home.root,
            env=_env(home.root),
            stdout=out,
            stderr=subprocess.STDOUT,
            check=False,
        )
    output = log.read_text()
    if "Nothing worth a film" in output:
        # A declined run exits 0 without a film: nothing to show, so nothing to record.
        raise SystemExit(f"{name}: the run made no film; see {log}")
    if result.returncode != 0:
        raise SystemExit(f"{name}: generate failed ({result.returncode}); see {log}")
    run_id = _RUN_ID.findall(output)[-1]
    fixture_of = {server: fixture for fixture, server in state["asset_ids"].items()}
    target = RECORDINGS / name
    target.mkdir(parents=True, exist_ok=True)
    attempt = _attempt_dir(home.root, started)
    for file in ATTEMPT_FILES:
        source = attempt / file
        if source.exists():
            data = _fixture_ids(json.loads(source.read_text()), fixture_of)
            (target / file.replace(".private", "")).write_text(
                json.dumps(data, indent=1, ensure_ascii=False) + "\n"
            )
    story = subprocess.run(  # noqa: S603
        [command[0], "runs", "story", run_id],
        cwd=home.root,
        env=_env(home.root),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    (target / "story.txt").write_text(story)
    films = sorted(home.videos.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
    FILMS.mkdir(parents=True, exist_ok=True)
    if films and films[-1].stat().st_mtime >= started:
        shutil.copy2(films[-1], FILMS / f"{name}.mp4")
    title = _TITLE.search(output)
    meta = {
        "title": (title["single"] or title["double"]) if title else None,
        "title_source": title["source"] if title else None,
        "memory_type": name,
        "arguments": MEMORY_TYPES[name],
        "seconds": round(time.time() - started),
    }
    (target / "run.json").write_text(json.dumps(meta, indent=1) + "\n")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=Path, required=True, help="real_seed's state.json")
    parser.add_argument("--home", type=Path, required=True, help="the recording home (kept)")
    parser.add_argument("--only", nargs="*", choices=sorted(MEMORY_TYPES), default=None)
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    home = _home(args.home, state, _operator_llm())
    logs = args.home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    for name in args.only or MEMORY_TYPES:
        meta = record(name, home, state, logs / f"{name}.log")
        print(f"{name}: recorded in {meta['seconds']} s", flush=True)


if __name__ == "__main__":
    main()
