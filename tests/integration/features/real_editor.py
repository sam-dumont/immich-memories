"""Films chosen by the real Basic editor: no scripted selection, no model, rules only.

The other film tests hand selection to the scripted stand-in (`tests/e2e/fake_editorial.py`).
Here `generate` runs the production pipeline from discovery to the finished file, and two
seams stay closed for a hermetic run:

- Basic prepares the period with eight small classifiers over a pinned 110 MB DINOv2 export,
  which `models fetch` downloads and no hermetic run has. The child prepares at
  `metadata_only`: the same rules reader on the dates, places, people, faces, favourites,
  OCR and pixel facts, without the classifiers' answers.
- Place names come from the fake Immich's reverse geocoder, never from Nominatim.

Everything else is the user's `generate`, against a fake Immich of the test's own.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import ALL_PICTURES, HELD_PICTURES, Picture
from tests.features.cli_harness import RUN_ID, CliResult, UserHome, basic_config, films_under
from tests.integration.features.cuts import Shot, story_of

_REAL_EDITOR = """
import sys

import immich_memories.analysis.place_geocoder as place_geocoder
import immich_memories.config_tiers as config_tiers

# WHY: Basic's classifiers run on the pinned DINOv2 export `models fetch` downloads; a
# hermetic run has none, so it prepares the period at metadata_only (no ONNX at all).
config_tiers.TIERS["basic"][config_tiers._PREPARATION] = "metadata_only"
# WHY: the fixture places are public and named by the fake Immich; nothing asks the internet.
place_geocoder.nominatim_fetch = lambda *_args, **_kwargs: lambda *_point: None

from immich_memories.cli import main

sys.argv = ["immich-memories", *sys.argv[1:]]
main()
"""

# Every picture the test's own fake Immich serves, by id.
SERVED: dict[str, Picture] = {p.asset_id: p for p in (*ALL_PICTURES, *HELD_PICTURES)}


@contextmanager
def library_with_held(root: Path, library: FakeImmichServer) -> Iterator[FakeImmichServer]:
    """A fake Immich of this test's own: the session's library plus the held pictures."""
    server = FakeImmichServer.start(root, media_of=library, held=HELD_PICTURES)
    try:
        yield server
    finally:
        server.close()
    assert server.refused == [], server.refused


def home_on(root: Path, server: FakeImmichServer, extra_env: dict[str, str]) -> UserHome:
    """A Basic install of this test's own, pointed at `server`."""
    home = UserHome(root, extra_env=tuple(extra_env.items()))
    home.write_config(basic_config(server.base_url, server.api_key, home))
    return home


@dataclass(frozen=True, slots=True)
class EditedFilm:
    """A finished `generate` through the real editor, and what its run recorded."""

    result: CliResult
    run_id: str
    film: Path
    plan: dict[str, Any]
    shots: tuple[Shot, ...]

    @property
    def output(self) -> str:
        return self.result.output

    @property
    def carriers(self) -> list[dict[str, Any]]:
        """The cut's shots as the plan keeps them, in playback order."""
        return list(self.plan["carriers"])

    def kept(self) -> list[Picture]:
        """The fixture picture behind each shot, in playback order."""
        return [SERVED[row["asset_id"]] for row in self.carriers]

    def moment_of(self, picture: Picture) -> set[str]:
        """Every picture the editor read as the same moment as a kept one, itself included."""
        row = next(r for r in self.carriers if r["asset_id"] == picture.asset_id)
        return {row["asset_id"], *row.get("members", ()), *row.get("moment_alternatives", ())}

    def pool(self) -> set[str]:
        """Every picture the editor could choose for this film.

        The snapshot keeps the whole window, the context a person film reads beside its pool;
        the pool is what the snapshot's own people condition lets through.
        """
        snapshot = _attempt_record(self.plan, "source-snapshot")
        wanted = set(snapshot.get("people") or ())
        either = snapshot.get("person_match") == "or"
        pool: set[str] = set()
        for entry in snapshot["sources"]:
            asset = entry["value"]["asset"] if entry["kind"] == "clip" else entry["value"]
            named = {person["name"] for person in asset.get("people") or ()}
            if not wanted or (wanted & named if either else wanted <= named):
                pool.add(asset["id"])
        return pool


def _attempt_record(plan: dict[str, Any], name: str) -> dict[str, Any]:
    directory = Path(plan["__attempt_dir__"])
    return json.loads((directory / f"{name}.private.json").read_text())


def generate(
    home: UserHome, *args: str, runner: Callable[..., CliResult] | None = None
) -> EditedFilm:
    """`immich-memories generate <args>` through the real editor; one film must come out.

    `runner` runs the child another way (`scripted_preparation.run_prepared`); default `run`.
    """
    before = set(films_under(home.videos)) if home.videos.exists() else set()
    result = (runner or run)(home, "generate", *args)
    assert result.returncode == 0, result.explain()
    added = [film for film in films_under(home.videos) if film not in before]
    assert len(added) == 1, f"expected one new film, got {added}\n{result.explain()}"
    found = RUN_ID.search(added[0].parent.name)
    assert found, added[0]
    run_id = found.group(0)
    return EditedFilm(result, run_id, added[0], plan_of(home, run_id), story_of(home, run_id))


def run(
    home: UserHome, *args: str, child: str = _REAL_EDITOR, env: dict[str, str] | None = None
) -> CliResult:
    """`immich-memories <args>` with the real editor in the child; never raises on exit.

    `child` is the script the child runs before the CLI (`_REAL_EDITOR` unless a test swaps
    other seams), and `env` adds to the home's environment.
    """
    completed = subprocess.run(  # noqa: S603 -- our own CLI, fixed argv
        [sys.executable, "-c", child, *args],
        capture_output=True,
        text=True,
        timeout=600,
        env=home.env(env),
        cwd=home.root,
        check=False,
    )
    return CliResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)


def plan_of(home: UserHome, run_id: str) -> dict[str, Any]:
    """The cut a run kept, read from the attempt the run names (`run.private.json`)."""
    for record in (home.root / ".immich-memories").rglob("run.private.json"):
        named = json.loads(record.read_text())
        if named.get("run_id") == run_id:
            plan = json.loads((record.parent / "plan.private.json").read_text())
            return plan | {"__attempt_dir__": str(record.parent)}
    raise AssertionError(f"no attempt names run {run_id}")
