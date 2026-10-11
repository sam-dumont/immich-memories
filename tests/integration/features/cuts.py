"""Read a kept cut back as fixture pictures: which ones play, in what order, for how long."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tests.e2e.fake_library import ALL_PICTURES, Picture
from tests.features.cli_harness import CliResult, UserHome

# `runs story` prints one line per shot: timecode, day, kind, seconds, then the reason,
# which the scripted editor writes as "<story title>: <the picture's caption>".
_SHOT = re.compile(
    r"^\s+(?P<at>\d+:\d\d)\s+(?P<day>\d{4}-\d\d-\d\d)\s+(?P<kind>photo|video)\s+"
    r"(?P<seconds>[\d.]+) s\s+(?P<why>.+)$",
    re.M,
)
_KEPT_RUN = re.compile(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})")


@dataclass(frozen=True, slots=True)
class Shot:
    """One line of `runs story`."""

    at: int
    day: str
    kind: str
    seconds: float
    why: str


@dataclass(frozen=True, slots=True)
class Cut:
    """A `generate --no-render`: its run, what it printed, and the shots `runs story` reads."""

    run_id: str
    result: CliResult
    shots: tuple[Shot, ...]

    @property
    def output(self) -> str:
        return self.result.output

    def pictures(self, library: tuple[Picture, ...] = ALL_PICTURES) -> list[Picture]:
        """The fixture picture behind each shot, in playback order."""
        return [picture_of(shot, library) for shot in self.shots]


def picture_of(shot: Shot, library: tuple[Picture, ...] = ALL_PICTURES) -> Picture:
    """The one picture of that day and kind whose caption ends the shot's reason.

    A scene's other shots share its caption; the scripted editor ships the scene's main shot,
    and a picture the owner kept says so in its reason.
    """
    kind = "video" if shot.kind == "video" else "still"
    found = [
        p
        for p in library
        if p.taken_at.startswith(shot.day)
        and p.kind == kind
        and shot.why.endswith(p.caption)
        and (p.shipped or "kept by the owner" in shot.why)
    ]
    assert len(found) == 1, f"{shot} matches {[p.asset_id for p in found]}"
    return found[0]


def story_of(home: UserHome, run_id: str) -> tuple[Shot, ...]:
    result = home.run("runs", "story", run_id)
    assert result.returncode == 0, result.explain()
    return tuple(
        Shot(
            at=int(m["at"].split(":")[0]) * 60 + int(m["at"].split(":")[1]),
            day=m["day"],
            kind=m["kind"],
            seconds=float(m["seconds"]),
            why=m["why"].strip(),
        )
        for m in _SHOT.finditer(result.stdout)
    )


def cut(home: UserHome, *args: str, env: dict[str, str] | None = None) -> Cut:
    """`generate <args> --no-render`, and the cut it kept read back through `runs story`."""
    result = home.run(*args, "--no-render", scripted_selection=True, env=env)
    assert result.returncode == 0, result.explain()
    found = _KEPT_RUN.findall(result.output)
    assert found, result.explain()
    return Cut(found[0], result, story_of(home, found[0]))
