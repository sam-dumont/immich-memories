"""The docs' view of the recorded films: one poster each and the numbers behind each cut.

Reads `tests/e2e/fixtures/recordings/<memory type>/` (the decisions of one real run, kept by
`scripts/record_demo_runs.py`) and `docs-site/static/demo/films/<memory type>.mp4` (the film
rendered from them), and writes:

- `docs-site/static/img/films/<memory type>.jpg`, a poster frame, which is also the page's
  social preview;
- `docs-site/src/data/recorded-films.json`, what the pool-to-film panel shows: how many
  pictures the run read, the moments and stories it saw, what it kept, and why it left the
  rest out.

Nothing here runs a model: rerun it after a new recording or a new render.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "tests" / "e2e" / "fixtures" / "recordings"
FILMS = ROOT / "docs-site" / "static" / "demo" / "films"
POSTERS = ROOT / "docs-site" / "static" / "img" / "films"
DATA = ROOT / "docs-site" / "src" / "data" / "recorded-films.json"

# The order the memory types page lists them in.
ORDER = (
    "monthly_highlights",
    "year_in_review",
    "season",
    "person_spotlight",
    "multi_person",
    "on_this_day",
    "holiday",
    "trip",
    "album",
    "special_day",
)
# A frame past the opening title and inside the cut, at this share of the film.
POSTER_AT = 0.3
# One line of `runs story`: start, day, kind, seconds.
_SHOT = re.compile(
    r"^\s+(?P<min>\d+):(?P<sec>\d\d)\s+\d{4}-\d\d-\d\d\s+\w+\s+(?P<len>[\d.]+) s", re.M
)
# The reasons the panel names; the rest are summed as "other reasons".
TOP_REASONS = 3


def _seconds(film: Path) -> float:
    out = subprocess.run(  # noqa: S603, S607 - our own film, fixed argv
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(film)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return round(float(out), 1)


def _frame(film: Path, at: float, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603, S607 - our own film, fixed argv
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(film),
         "-frames:v", "1", "-q:v", "4", str(target)],
        check=True,
    )  # fmt: skip


def _shot_middles(story: str) -> list[float]:
    """The middle second of every shot `runs story` lists."""
    return [int(m["min"]) * 60 + int(m["sec"]) + float(m["len"]) / 2 for m in _SHOT.finditer(story)]


# Shots per contact sheet, as (columns, rows), by how many shots the film has.
_GRIDS = ((1, (1, 1)), (2, (2, 1)), (4, (2, 2)), (6, (3, 2)))
TILE = (426, 240)


def _grid(shots: int) -> tuple[int, int]:
    return next((grid for most, grid in _GRIDS if shots <= most), _GRIDS[-1][1])


def _poster(film: Path, story: str, seconds: float, target: Path) -> None:
    """A contact sheet of the film: one frame from each of its shots, spread across it.

    It shows what the run made of the period at a glance (many moments, one film) where a
    single frame would make one face stand for the whole film.
    """
    from PIL import Image, ImageOps

    middles = _shot_middles(story) or [seconds * POSTER_AT]
    columns, rows = _grid(len(middles))
    count = columns * rows
    picks = [middles[round(i * (len(middles) - 1) / max(count - 1, 1))] for i in range(count)]
    sheet = Image.new("RGB", (columns * TILE[0], rows * TILE[1]), "black")
    with tempfile.TemporaryDirectory() as scratch:
        for n, at in enumerate(picks):
            frame = Path(scratch) / f"{n}.jpg"
            _frame(film, at, frame)
            tile = ImageOps.fit(Image.open(frame).convert("RGB"), TILE)
            sheet.paste(tile, ((n % columns) * TILE[0], (n // columns) * TILE[1]))
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, quality=85)


def _reasons(left_out: dict[str, Any]) -> list[dict[str, Any]]:
    """Left-out pictures by reason, the commonest first; the tail summed."""
    counts = Counter(str(reason).split(":")[0].strip() for reason in left_out.values())
    top = [{"reason": reason, "pictures": n} for reason, n in counts.most_common(TOP_REASONS)]
    rest = sum(counts.values()) - sum(row["pictures"] for row in top)
    return top + ([{"reason": "other reasons", "pictures": rest}] if rest else [])


def film_facts(name: str) -> dict[str, Any] | None:
    folder = RECORDINGS / name
    film = FILMS / f"{name}.mp4"
    if not (folder / "plan.json").is_file() or not film.is_file():
        return None
    plan = json.loads((folder / "plan.json").read_text())
    trace = json.loads((folder / "selection-trace.json").read_text())
    run = json.loads((folder / "run.json").read_text())
    projection = json.loads((folder / "render-projection.json").read_text())
    eligibility = next(p for p in trace["editorial_passes"] if p["name"] == "source-eligibility")
    seconds = _seconds(film)
    _poster(film, (folder / "story.txt").read_text(), seconds, POSTERS / f"{name}.jpg")
    return {
        "memory_type": name,
        "title": run.get("title"),
        "arguments": run["arguments"],
        "film": f"/demo/films/{name}.mp4",
        "poster": f"/img/films/{name}.jpg",
        "seconds": seconds,
        "read": len(eligibility["kept_ids"]),
        "moments": plan.get("families", {}).get("episodes_before"),
        "stories": len(plan.get("chapters", [])),
        "kept": len(projection["selected_ids"]),
        "left_out": _reasons(plan.get("left_out", {})),
    }


def main() -> None:
    rows = [facts for name in ORDER if (facts := film_facts(name)) is not None]
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(rows)} films: {DATA.relative_to(ROOT)} and {len(rows)} posters")


if __name__ == "__main__":
    main()
