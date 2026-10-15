#!/usr/bin/env python3
"""Write the Remotion demo's fixture module from the hermetic library.

The demo recreates the UI in React over the same pictures the fake Immich
serves, so the two must agree: the thesis, the cut in playback order, the pool
page's first page and its counters. This exports them into
``docs-site/remotion/src/fixture.ts`` so the demo cannot drift from the fixture.
Run it through ``make demo-fixture``.

With ``IMMICH_MEMORIES_E2E_RECORDING`` naming a recording (the Makefile sets it
to the month the screenshots replay) the cut is that recorded real run: its
one-line summary, its pictures, stories and reasons, and for every other picture
the reason the run gave. Without one, it is the script in
``tests/e2e/fake_library``.

It also measures the film the demo ends on, because the scene that plays it
cannot be told its shape in a constant: a re-cut moves every one of them.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e import fake_editorial  # noqa: E402
from tests.e2e.fake_immich import ALBUMS, TIMELINE_ASSETS  # noqa: E402
from tests.e2e.fake_library import (  # noqa: E402
    BY_ID,
    CARRIERS,
    LIBRARY,
    LIBRARY_DIR,
    MONTH,
    STORIES,
    STORY_OF,
    THESIS,
    YEAR,
    pool_line,
    summary_line,
)

from immich_memories.api.models import Asset  # noqa: E402
from immich_memories.config.loader import Config  # noqa: E402
from immich_memories.operations.reader_words import stage_words  # noqa: E402
from immich_memories.operations.storyboard import Storyboard, storyboard_from_plan  # noqa: E402
from immich_memories.processing.editorial_timing import (  # noqa: E402
    bind_editorial_timeline,
    build_editorial_timing_policy,
)

# The pass the fixture's editorial route records its rejections under; the pool
# page prints the reader's words for it, not the engine's name.
DROP_STAGE = "picture_review"

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs-site" / "remotion" / "src" / "fixture.ts"
FILM = ROOT / "docs-site" / "remotion" / "public" / "output-preview.mp4"
REMOTION_LIBRARY = ROOT / "docs-site" / "remotion" / "public" / "library"
# Past a clip's first frame, which is often a fade-in or a blur, and inside its shortest take.
POSTER_SECONDS = 1.5
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
POOL_PAGE = 20
# The scripted cut is asked for two minutes, as the hermetic UI does.
SCRIPTED_REQUEST_SECONDS = 120
# What `fake_editorial._replay` says of a picture the recorded run never mentioned.
_UNRECORDED = "not in the recorded cut"
# How many other pictures of a shot's moment the inspector offers, as in the fake editor.
ALTERNATIVES_PER_SHOT = 3
WEIGHT_RANK = {"dominant": 0, "major": 1, "minor": 2, "glimpse": 3}

# How often the film is sampled when looking for the end of its pictures. The
# ending card is several seconds long, so twice a second is far finer than the
# answer needs and still one decode of the file.
FILM_SAMPLE_FPS = 2


def _still(picture) -> str:
    """The picture the demo draws for this one: a clip is drawn as a frame from it.

    The frame is cut next to the copy of the library `make demo-ui-install` makes, which is
    where Remotion reads it from.
    """
    relative = picture.source.relative_to(LIBRARY_DIR)
    if relative.suffix != ".mp4":
        return f"library/{relative}"
    poster = relative.with_suffix(".jpg")
    target = REMOTION_LIBRARY / poster
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603
        [
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", str(POSTER_SECONDS),
            "-i", str(picture.source), "-frames:v", "1", "-q:v", "2", str(target),
        ],
        check=True,
    )  # fmt: skip
    return f"library/{poster}"


def _suggestion_facts() -> dict[str, object]:
    """What `auto suggest` counts on the fake Immich: the album's own row, and Kit's July days.

    The album detector reads Immich's `assetCount` and its first and last day; the person
    detector counts the person's pictures per local day (`material.person_days_in`).
    """
    album = ALBUMS[0]
    kit_days: dict[str, int] = {}
    for asset in TIMELINE_ASSETS:
        day = asset["localDateTime"][:10]
        if day[:7] == f"{YEAR}-{MONTH:02d}" and "person-kit" in {p["id"] for p in asset["people"]}:
            kit_days[day] = kit_days.get(day, 0) + 1
    return {
        "album_name": album["albumName"],
        "album_pictures": album["assetCount"],
        "album_first": album["startDate"][:10],
        "album_last": album["endDate"][:10],
        "kit_pictures": sum(kit_days.values()),
        "kit_days": len(kit_days),
    }


def _taken_label(taken_at: str) -> str:
    return f"{MONTHS[int(taken_at[5:7]) - 1]} {taken_at[8:10]} {taken_at[11:16]}"


@dataclass
class Cut:
    """The cut the demo shows, from the recording or from the script."""

    thesis: str
    summary: str
    pictures: list  # fake_library pictures, in playback order
    story_of: dict[str, str]  # asset id -> story title
    reason_of: dict[str, str]  # asset id -> why it is in the cut
    alternatives: dict[str, list[str]]  # asset id -> other pictures of its moment
    stories: list[dict]
    board: Storyboard
    left_out: dict[str, str]  # asset id -> why the run left it out
    cut_seconds: int
    request_seconds: int  # the length the cut was asked for


def _board(carriers: list[dict], render_timing: dict | None = None):
    """The request's timeline over a cut's carriers: the recording's own, else a two-minute one."""
    assets = {raw["id"]: Asset.model_validate(raw) for raw in TIMELINE_ASSETS}
    if render_timing is None:
        policy = build_editorial_timing_policy(
            config=Config(),
            target_seconds=SCRIPTED_REQUEST_SECONDS,
            memory_type="monthly_highlights",
            date_start=date(YEAR, MONTH, 1),
            date_end=date(YEAR, MONTH, 31),
        )
        timeline = policy.resolve(carriers, assets)
        render_timing = bind_editorial_timeline(
            policy, timeline, [carrier["asset_id"] for carrier in carriers]
        )
    return storyboard_from_plan({"carriers": carriers, "render_timing": render_timing}, None)


def _scripted_cut() -> Cut:
    carriers = [
        {
            "asset_id": p.asset_id,
            "seconds": p.seconds,
            "taken": p.taken_at,
            "kind": "video" if p.is_video else "still",
        }
        for p in CARRIERS
    ]
    return Cut(
        thesis=THESIS,
        summary=summary_line(),
        pictures=list(CARRIERS),
        story_of={p.asset_id: STORY_OF[p.asset_id].title for p in CARRIERS},
        reason_of={p.asset_id: p.caption for p in CARRIERS},
        alternatives={p.asset_id: fake_editorial._siblings(p) for p in CARRIERS},
        stories=[
            {"title": story.title, "weight": story.weight, "purpose": story.purpose}
            for story in STORIES
        ],
        board=_board(carriers),
        left_out={p.asset_id: p.drop_reason for p in LIBRARY if p.drop_reason},
        cut_seconds=int(sum(p.seconds for p in CARRIERS)),
        request_seconds=SCRIPTED_REQUEST_SECONDS,
    )


def _recorded_cut(recorded: dict) -> Cut:
    """The recorded real run: its thesis, cut order, stories, reasons and left-out reasons."""
    thesis, selected = fake_editorial.active_cut()
    plan = recorded["plan"]
    by_id = {carrier["asset_id"]: carrier for carrier in plan["carriers"]}
    carriers = [by_id[asset_id] for asset_id in selected]
    episodes = {episode["episode"]: episode for episode in plan["story"]["episodes"]}
    used = {carrier["story_episode"] for carrier in carriers}
    # The plan lists its episodes heaviest first; keep that order, weight breaking no ties.
    stories = sorted(
        (episode for episode in plan["story"]["episodes"] if episode["episode"] in used),
        key=lambda episode: WEIGHT_RANK.get(episode["weight"], len(WEIGHT_RANK)),
    )
    # The replay's own rule for what the pool page says about a picture it left out; where it
    # only says "not in the recorded cut", the plan's own reason is the more useful line.
    _, dropped = fake_editorial._replay([SimpleNamespace(id=p.asset_id) for p in LIBRARY], recorded)
    plan_reasons = plan.get("left_out", {})
    left_out = {
        asset_id: reason
        if asset_id not in plan_reasons or reason != _UNRECORDED
        else plan_reasons[asset_id]
        for asset_id, reason in dropped
    }
    return Cut(
        thesis=thesis,
        summary=f"{len(used)} stories, {len(carriers)} pictures",
        pictures=[BY_ID[asset_id] for asset_id in selected],
        story_of={c["asset_id"]: episodes[c["story_episode"]]["title"] for c in carriers},
        reason_of={c["asset_id"]: c["why"] for c in carriers},
        alternatives={
            c["asset_id"]: [a for a in c["moment_alternatives"] if a in BY_ID][
                :ALTERNATIVES_PER_SHOT
            ]
            for c in carriers
        },
        stories=[
            {"title": e["title"], "weight": e["weight"], "purpose": e["purpose"]} for e in stories
        ],
        board=_board(carriers, plan["render_timing"]),
        left_out=left_out,
        cut_seconds=int(sum(c["seconds"] for c in carriers)),
        request_seconds=int(plan["target_seconds"]),
    )


def _the_cut() -> Cut:
    recorded = fake_editorial.recording()
    return _scripted_cut() if recorded is None else _recorded_cut(recorded)


def _outcome(picture, cut: Cut, timecodes: dict[str, str]) -> str:
    """The line the pool prints under a thumbnail, in CandidateFates' words."""
    if picture.asset_id in cut.reason_of:
        return f"In the cut at {timecodes[picture.asset_id]}: {cut.reason_of[picture.asset_id]}"
    reason = cut.left_out.get(picture.asset_id) or "not part of any story the month tells"
    return f"Left out at {stage_words(DROP_STAGE)}: {reason}"


def _edge_energy() -> list[tuple[float, float]]:
    """Per-sample sharpness of the film, as (seconds, energy).

    `edgedetect` reads a flat 0 on the film's blurred ending card and 8 to 12 on
    a photograph, which is what makes the end of the pictures findable rather
    than guessable.
    """
    probe = subprocess.run(  # noqa: S603
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(FILM),
            "-vf",
            f"fps={FILM_SAMPLE_FPS},edgedetect=mode=wires,signalstats,"
            "metadata=print:key=lavfi.signalstats.YAVG:file=-",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    samples = re.findall(r"pts_time:([0-9.]+)\s*\nlavfi\.signalstats\.YAVG=([0-9.]+)", probe)
    return [(float(time), float(energy)) for time, energy in samples]


def _film_facts() -> dict[str, object]:
    """What the demo's last scene needs to know about the film it plays.

    `OutputPreviewScene` plays the film's closing seconds and must stop on a
    photograph: the film ends on a blurred card, and a demo that ends on mush is
    the README's first impression. Both numbers move on every re-cut, so both
    are measured here rather than typed there.
    """
    duration = float(
        subprocess.run(  # noqa: S603
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(FILM),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    samples = _edge_energy()
    energies = sorted(energy for _, energy in samples)
    picture_level = energies[len(energies) // 2]
    sharp = [time for time, energy in samples if energy >= picture_level / 2]
    return {
        "seconds": round(duration, 2),
        # The last sample still showing a photograph, not the crossfade into the card.
        "pictures_end": round(max(sharp), 2),
        # The UI's own rounding, from `_format_file_size` in ui/pages/_step4_generate.py.
        "size": f"{FILM.stat().st_size / 1_048_576:.0f} MB",
    }


def _shots(cut: Cut) -> list[dict]:
    shots = []
    previous_month = None
    timed = {shot.asset_id: shot for shot in cut.board.shots}
    for picture in cut.pictures:
        month = picture.day[:7]
        shot = {
            "picture": _still(picture),
            "day": picture.taken_at[:10],
            "motion": picture.is_video,
            "seconds": round(timed[picture.asset_id].seconds, 2),
            "start": timed[picture.asset_id].start,
            "story": cut.story_of[picture.asset_id],
            "reason": cut.reason_of[picture.asset_id],
            "alternatives": [
                _still(BY_ID[asset_id]) for asset_id in cut.alternatives[picture.asset_id]
            ],
        }
        if month != previous_month:
            shot["chapter"] = f"{MONTHS[int(month[5:7]) - 1]} {month[:4]}".replace("Jul ", "July ")
            previous_month = month
        shots.append(shot)
    return shots


def _pool(cut: Cut, shots: list[dict], timecodes: dict[str, str]) -> list[dict]:
    """The pool page's first page, then the pictures the inspector offers in place of a shot."""
    ids = [picture.asset_id for picture in LIBRARY[:POOL_PAGE]]
    for alternatives in cut.alternatives.values():
        ids += [asset_id for asset_id in alternatives if asset_id not in ids]
    return [
        {
            "picture": _still(picture),
            "motion": picture.is_video,
            "taken": _taken_label(picture.taken_at),
            "file": picture.filename,
            "favourite": picture.is_favorite,
            "ticked": picture.asset_id in cut.reason_of,
            "seconds": int(picture.seconds),
            "outcome": _outcome(picture, cut, timecodes),
        }
        for picture in map(BY_ID.__getitem__, ids)
    ]


def main() -> None:
    cut = _the_cut()
    board = cut.board
    shots = _shots(cut)
    swapped, removed = fake_editorial.active_edit()
    timecodes = {shot.asset_id: shot.timecode for shot in board.shots}
    pool = _pool(cut, shots, timecodes)
    videos = sum(1 for picture in LIBRARY if picture.is_video)
    stories = cut.stories
    film = _film_facts()
    suggestions = _suggestion_facts()
    body = "\n".join(
        [
            "// Generated by scripts/export-demo-fixture.py from tests/e2e/fake_library.py, the",
            "// recorded run it replays and docs-site/remotion/public/output-preview.mp4.",
            "// Do not edit: run `make demo-fixture` after the fixture library or the film changes.",
            "",
            "export type Shot = {",
            "  picture: string;",
            "  day: string;",
            "  motion: boolean;",
            "  seconds: number;",
            "  start: number;",
            "  story: string;",
            "  reason: string;",
            "  /** Other pictures of this moment the inspector offers, all in POOL. */",
            "  alternatives: string[];",
            "  /** Set on the first picture of a month: the real page prints a chapter label. */",
            "  chapter?: string;",
            "};",
            "",
            "/** A weighed story, heaviest first, as the Stories view lists them. */",
            "export type Story = {",
            "  title: string;",
            "  weight: string;",
            "  purpose: string;",
            "};",
            "",
            "export type PoolCard = {",
            "  picture: string;",
            "  motion: boolean;",
            "  taken: string;",
            "  file: string;",
            "  favourite: boolean;",
            "  ticked: boolean;",
            "  seconds: number;",
            "  /** What the saved cut did with this picture, as the pool page prints it. */",
            "  outcome: string;",
            "};",
            "",
            f"export const THESIS = {json.dumps(cut.thesis)};",
            f"export const SUMMARY_LINE = {json.dumps(cut.summary)};",
            f"export const POOL_LINE = {json.dumps(pool_line())};",
            f"export const POOL_TOTAL = {len(LIBRARY)};",
            f"export const POOL_VIDEOS = {videos};",
            f"export const POOL_PAGE = {POOL_PAGE};",
            "/** What the suggestions page counts: the album's own row and Kit's pictures in the month. */",
            f"export const ALBUM_NAME = {json.dumps(suggestions['album_name'])};",
            f"export const ALBUM_PICTURES = {suggestions['album_pictures']};",
            f"export const ALBUM_FIRST = {json.dumps(suggestions['album_first'])};",
            f"export const ALBUM_LAST = {json.dumps(suggestions['album_last'])};",
            f"export const KIT_PICTURES = {suggestions['kit_pictures']};",
            f"export const KIT_DAYS = {suggestions['kit_days']};",
            f"export const REQUEST_SECONDS = {cut.request_seconds};",
            f"export const CUT_COUNT = {len(shots)};",
            f"export const CUT_SECONDS = {cut.cut_seconds};",
            f"export const CUT_FILM_SECONDS = {board.film_seconds};",
            "/** The pictures' own seconds, and what the titles leave them: the edit bar's two numbers. */",
            f"export const CUT_CONTENT_SECONDS = {round(board.total_seconds, 2)};",
            f"export const CUT_CONTENT_BUDGET = {json.dumps(board.content_budget_seconds)};",
            "/** The shots the edit scene swaps for another picture of the moment, and removes. */",
            f"export const EDIT_SWAPPED = {swapped};",
            f"export const EDIT_REMOVED = {removed};",
            "",
            "/** How long output-preview.mp4 runs, measured. */",
            f"export const FILM_SECONDS = {film['seconds']};",
            "/** The last second of it that still shows a photograph, before the ending card. */",
            f"export const FILM_PICTURES_END = {film['pictures_end']};",
            "/** Its size, in the words the completion page prints. */",
            f"export const FILM_SIZE = {json.dumps(film['size'])};",
            "",
            f"export const SHOTS: Shot[] = {json.dumps(shots, indent=2, ensure_ascii=False)};",
            f"export const STORIES: Story[] = {json.dumps(stories, indent=2, ensure_ascii=False)};",
            f"export const POOL: PoolCard[] = {json.dumps(pool, indent=2, ensure_ascii=False)};",
            "",
        ]
    )
    OUT.write_text(body)
    print(
        f"wrote {OUT.relative_to(OUT.parents[3])}: {len(shots)} shots, {len(pool)} pool cards, "
        f"film {film['seconds']}s with pictures to {film['pictures_end']}s ({film['size']})"
    )


if __name__ == "__main__":
    main()
