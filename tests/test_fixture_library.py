"""The fixture library is exactly what CREDITS.md and library.json say it is.

Every photograph and clip the demos and screenshots show ships with the
repository, so each one must be a file whose provenance is on record. This pins
the record to the bytes (every credited file exists and hashes as credited,
every file present is credited, every licence is CC0 or CC BY) and pins what
the fake Immich serves to what the files say: a picture is served at the place
its file was taken, or at no place (one indoor series may stand for the
household's home), and at its own capture time moved by whole days at most.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from tests.e2e.fake_library import (
    CARRIERS,
    CAST,
    HOME,
    LIBRARY,
    LIBRARY_DIR,
    MANIFEST,
    STORIES,
    STORY_OF,
    TRIP,
    TRIP_DAYS,
    TRIP_SET,
)

_ROW = re.compile(
    r"^\| `([^`]+)` \| (.+?) \| (.+?) \| (https://\S+) \| (CC0|CC BY [234]\.0) \| `([0-9a-f]{64})` \|$"
)
# Big enough to show culling at the scale of a phone's month, small enough to clone:
# a thousand pictures, most at 500 px, the ones a cut can reach at 1280 (about 55 MB).
_MAX_LIBRARY_MB = 60


def _credited() -> dict[str, tuple[str, str, str, str, str]]:
    rows = {}
    for line in (LIBRARY_DIR / "CREDITS.md").read_text().splitlines():
        match = _ROW.match(line)
        if match:
            name, title, author, url, licence, digest = match.groups()
            rows[name] = (title, author, url, licence, digest)
    return rows


def _files() -> set[str]:
    return {
        str(path.relative_to(LIBRARY_DIR))
        for pattern in ("*.jpg", "clips/*.mp4")
        for path in LIBRARY_DIR.glob(pattern)
    }


def _manifest() -> dict[str, dict]:
    return {record["stem"]: record for record in json.loads(MANIFEST.read_text())}


def test_every_credited_file_exists_and_hashes_as_credited() -> None:
    rows = _credited()
    assert rows, "CREDITS.md holds no rows"
    for name, (_title, _author, _url, _licence, digest) in rows.items():
        path = LIBRARY_DIR / name
        assert path.exists(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name


def test_every_file_in_the_library_is_credited_under_cc0_or_cc_by() -> None:
    rows = _credited()
    assert _files() == set(rows), _files() ^ set(rows)
    assert {row[3] for row in rows.values()} <= {"CC0", "CC BY 2.0", "CC BY 3.0", "CC BY 4.0"}
    assert all(row[1].strip() for row in rows.values()), "every file names its author"


def test_no_library_file_is_one_the_repository_ignores() -> None:
    """A file `.gitignore` swallows exists on the machine that built it and nowhere else."""
    names = sorted(_files())
    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],  # noqa: S607
        input="\n".join(str(LIBRARY_DIR / name) for name in names),
        capture_output=True,
        text=True,
        check=False,
        cwd=LIBRARY_DIR,
    ).stdout.split()
    assert ignored == [], ignored


def test_the_library_stays_small_enough_to_clone() -> None:
    total = sum((LIBRARY_DIR / name).stat().st_size for name in _files())
    assert total < _MAX_LIBRARY_MB * 1024 * 1024, f"{total / 1e6:.1f} MB"


def test_a_picture_is_served_where_its_file_was_taken_or_nowhere() -> None:
    """Outdoors a place is the file's own or none. One indoor series, one shoot in one
    interior, may stand for the household's home (owner's rule), and only at HOME."""
    manifest = _manifest()
    home_sets = set()
    for picture in LIBRARY:
        if picture.place is None:
            continue
        # A Live Photo still is made from a library file and answers for that file's place.
        record = manifest[picture.asset_id if picture.asset_id in manifest else picture.source_id]
        if record["gps_from"] == "home":
            home_sets.add(record["set"])
            assert (picture.place.latitude, picture.place.longitude) == (
                HOME.latitude,
                HOME.longitude,
            ), picture.asset_id
            continue
        source = record["source_gps"]
        assert record["gps_from"] == "file", picture.asset_id
        assert source is not None, f"{picture.asset_id} is served at a place its file lacks"
        assert [picture.place.latitude, picture.place.longitude] == source, picture.asset_id
    assert len(home_sets) <= 1, f"more than one series stands for home: {sorted(home_sets)}"


def test_a_picture_keeps_its_own_hour_moved_by_whole_days_one_offset_per_set() -> None:
    manifest = _manifest()
    shifts: dict[str, set[int]] = defaultdict(set)
    for picture in LIBRARY:
        if picture.asset_id not in manifest:
            continue  # a Live Photo made from a library file, on a day of its own
        record = manifest[picture.asset_id]
        shifts[record["set"]].add(record["shift_days"])
        if record["time_from"] != "file":
            continue
        moved = datetime.fromisoformat(record["taken_local"]) - datetime.fromisoformat(
            record["source_taken"]
        )
        assert (moved.seconds, moved.days) == (0, record["shift_days"]), picture.asset_id
    assert all(len(days) == 1 for days in shifts.values()), dict(shifts)
    assert shifts[TRIP_SET] == {0}, "the trip is served at the minute it was taken"


def test_the_month_is_july_and_the_trip_is_one_photographers_twenty_days() -> None:
    assert {picture.day[:7] for picture in LIBRARY} == {"2025-07"}
    assert {picture.taken_at[:7] for picture in LIBRARY} == {"2025-07"}
    assert (TRIP[0].day, TRIP[-1].day) == ("2025-07-12", "2025-07-31")
    manifest = _manifest()
    assert len({manifest[p.asset_id]["source"]["author"] for p in TRIP}) == 1


def test_the_library_is_big_enough_to_show_culling() -> None:
    assert len(LIBRARY) >= 1000
    assert sum(1 for picture in LIBRARY if picture.is_video) >= 7
    assert 15 <= len(CARRIERS) <= 30
    # Every story with a purpose carries at least one picture, in capture order.
    assert {story.key for story in STORIES} == {story.key for story in STORY_OF.values()}
    assert [picture.taken_at for picture in CARRIERS] == sorted(
        picture.taken_at for picture in CARRIERS
    )


def test_trip_detection_finds_exactly_the_road_north() -> None:
    from immich_memories.analysis.trip_detection import detect_trips
    from immich_memories.api.models import Asset
    from tests.e2e.fake_immich import _asset_payload

    assets = [Asset.model_validate(_asset_payload(picture)) for picture in LIBRARY]
    trips = detect_trips(assets, HOME.latitude, HOME.longitude)
    assert [(trip.start_date.isoformat(), trip.end_date.isoformat()) for trip in trips] == [
        TRIP_DAYS
    ]


def test_every_named_person_has_a_face_pinned_to_them() -> None:
    for picture in LIBRARY:
        assert set(picture.people) <= set(CAST), picture.asset_id
        pinned = sorted(face.person for face in picture.faces)
        assert pinned == sorted(picture.people), picture.asset_id
        for face in picture.faces:
            assert 0 <= face.x <= face.x + face.w <= 1, picture.asset_id
            assert 0 <= face.y <= face.y + face.h <= 1, picture.asset_id
    assert all(any(name in picture.people for picture in LIBRARY) for name in CAST)


def test_every_picture_has_a_reason_to_be_in_or_out() -> None:
    for picture in LIBRARY:
        assert picture.caption
        assert (picture.story_key is None) != (picture.drop_reason is None), picture.asset_id


def test_the_module_refuses_to_stand_apart_from_its_pictures(tmp_path: Path) -> None:
    """A copy without the directory must fail loudly, not read as an empty month (#881)."""
    package = tmp_path / "tests" / "e2e"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").touch()
    (package / "__init__.py").touch()
    shutil.copy(LIBRARY_DIR.parent.parent / "fake_library.py", package / "fake_library.py")

    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import tests.e2e.fake_library",
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert proc.returncode != 0
    assert "the library is its files" in proc.stderr
