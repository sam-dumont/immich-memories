"""Feature tests: automation over HTTP, from the decision to the film in Immich and the message.

Every command is the real CLI in a child process with its own sealed HOME, reading the
fixture library from the session's Immich over HTTP. `auto run` starts a real
`generate` child, which renders with FFmpeg, uploads to a fake Immich of its own and sends its
completion message to a loopback Apprise JSON target. Two things are pinned in the
children, as the other feature renders pin selection: the day discovery runs on (the
fixture library is June 2024) and the scripted editor in the `generate` child.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.fake_immich import ALBUMS, FakeImmichServer
from tests.features.automation_library import LocalHttp
from tests.features.cli_harness import CliResult, OutboundTrap, UserHome, basic_config
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import QUIET_DAY, day_args, own_immich

# Each upload test reads its film back from the upload log of a fake Immich of its own, one
# no other test uploaded to, and links to the id that fake gave it.
_UPLOADS_TO_ITS_OWN_FAKE = pytest.mark.fake_immich_only(
    "reads its film from the upload log of a fake Immich that holds no other test's upload"
)

# The child: pin discovery's day (argv[1], blank for the real one), and give the `generate`
# child it starts the scripted editor (argv[2] == "scripted"), then run the real CLI.
_CHILD = """
import sys
from datetime import date
from unittest.mock import patch

today, scripted = sys.argv[1], sys.argv[2] == "scripted"
if today:
    class _Today(date):
        @classmethod
        def today(cls):
            return date.fromisoformat(today)

    # WHY: the wall clock; the fixture library's trip ends on a fixed day in 2024.
    patch("immich_memories.automation.candidate_discovery.date", _Today).start()
if scripted:
    editor = (
        "import sys\\n"
        "from tests.e2e.fake_editorial import install_fake_editorial_route\\n"
        "install_fake_editorial_route(stage_seconds=0.0)\\n"
        "from immich_memories.cli import main\\n"
        "sys.argv = ['immich-memories', *sys.argv[1:]]\\n"
        "main()\\n"
    )
    # The `generate` child still renders, uploads and notifies for real.
    # WHY: selection, scripted as in every feature render (the launch check's editor).
    patch(
        "immich_memories.automation.generation_request.self_command",
        lambda: [sys.executable, "-c", editor],
    ).start()

from immich_memories.cli import main

sys.argv = ["immich-memories", *sys.argv[3:]]
main()
"""

PUBLIC_URL = "https://photos.example.test"


def _run(home: UserHome, *args: str, today: str = "", scripted: bool = False) -> CliResult:
    completed = subprocess.run(  # noqa: S603 -- our own CLI, fixed argv
        [sys.executable, "-c", _CHILD, today, "scripted" if scripted else "", *args],
        capture_output=True,
        text=True,
        timeout=600,
        env=home.env(),
        cwd=home.root,
        check=False,
    )
    return CliResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)


@pytest.fixture
def sink() -> Iterator[LocalHttp]:
    """An Apprise `json://` target on the loopback: every message lands here."""
    server = LocalHttp()
    yield server
    server.close()


def _home(
    root: Path, immich: LibraryServer | FakeImmichServer, trap: OutboundTrap, **advanced: Any
) -> UserHome:
    home = UserHome(root, extra_env=tuple(trap.env().items()))
    config = basic_config(immich.base_url, immich.api_key, home)
    for key, value in advanced.items():
        if key == "public_url":
            config["immich"]["public_url"] = value
        else:
            config["advanced"][key] = value
    home.write_config(config)
    return home


def _notifying(sink: LocalHttp) -> dict[str, Any]:
    port = sink.url.rsplit(":", 1)[1]
    return {"enabled": True, "urls": [f"json://127.0.0.1:{port}/"]}


def _suggested(home: UserHome, today: str = "") -> list[dict[str, Any]]:
    result = _run(home, "auto", "suggest", "--json", "--limit", "50", today=today)
    assert result.returncode == 0, result.explain()
    return json.loads(result.stdout)


# ── the trip detector ────────────────────────────────────────────────────

# The fixture household drives to the Alps on 21 June 2024 and comes home on 27 June.
LAKE_TRIP = "2024-06-21 to 2024-06-27"


@pytest.mark.feature("detector.trip")
def test_a_trip_is_proposed_7_days_after_coming_home(
    tmp_path: Path, immich: LibraryServer, outbound_trap: OutboundTrap
) -> None:
    home = _home(tmp_path / "home", immich, outbound_trap)

    trips = [r for r in _suggested(home, today="2024-07-04") if r["category"] == "trip"]

    assert [r["date_range"] for r in trips] == [LAKE_TRIP]
    assert trips[0]["reason"].startswith("7-day trip to ")


@pytest.mark.feature("detector.trip")
def test_a_trip_6_days_after_coming_home_waits(
    tmp_path: Path, immich: LibraryServer, outbound_trap: OutboundTrap
) -> None:
    home = _home(tmp_path / "home", immich, outbound_trap)

    rows = _suggested(home, today="2024-07-03")

    assert [r for r in rows if r["category"] == "trip"] == []


@pytest.mark.feature("detector.trip")
def test_a_trip_more_than_a_year_old_is_not_proposed(
    tmp_path: Path, immich: LibraryServer, outbound_trap: OutboundTrap
) -> None:
    home = _home(tmp_path / "home", immich, outbound_trap)

    rows = _suggested(home, today="2025-07-04")

    assert [r for r in rows if r["category"] == "trip"] == []


# ── auto run, end to end ─────────────────────────────────────────────────


@pytest.mark.feature("automation.run")
@pytest.mark.feature("automation.upload")
@pytest.mark.feature("notifications.on-completion")
@pytest.mark.feature("notifications.upload-link")
@_UPLOADS_TO_ITS_OWN_FAKE
def test_auto_run_renders_delivers_and_announces_the_film_with_its_immich_link(
    tmp_path: Path, delivery_immich: FakeImmichServer, outbound_trap: OutboundTrap, sink: LocalHttp
) -> None:
    home = _home(
        tmp_path / "home",
        delivery_immich,
        outbound_trap,
        automation={"upload_to_immich": True},
        notifications=_notifying(sink),
        public_url=PUBLIC_URL,
    )
    album = next(r for r in _suggested(home) if r["category"] == "album")

    result = _run(home, "auto", "run", "--candidate", album["memory_key"], "--quiet", scripted=True)

    assert result.returncode == 0, result.explain()
    decision = json.loads(result.stdout.strip().splitlines()[-1])
    assert (decision["outcome"], decision["candidate_key"]) == ("completed", album["memory_key"])
    # This test's own Immich: its one upload is this film, whatever ran before it.
    delivered = delivery_immich.uploads
    assert len(delivered) == 1 and delivered[0].content_type == "video/mp4"
    asset_id = "uploaded-1"
    messages = sink.posted()
    assert [m["title"] for m in messages] == ["Memory Generated: Album"]
    assert f"Watch in Immich: {PUBLIC_URL}/photos/{asset_id}" in messages[0]["message"]


# ── a film made by hand ──────────────────────────────────────────────────


@dataclass(frozen=True)
class _HandMade:
    home: UserHome
    result: CliResult
    messages: list[Any]
    asset_id: str
    proposed_before: list[dict[str, Any]]
    immich_url: str


@pytest.fixture(scope="module")
def hand_made_album(
    tmp_path_factory: pytest.TempPathFactory,
    fake_immich: FakeImmichServer,
    outbound_trap: OutboundTrap,
) -> Iterator[_HandMade]:
    """`generate --from-album` the fixture's lake week, uploaded, with notifications on.

    It uploads to an Immich of its own, so its film is that service's first upload
    whatever else ran on this worker.
    """
    sink = LocalHttp()
    with own_immich(tmp_path_factory.mktemp("hand-made-immich"), fake_immich) as immich:
        home = _home(
            tmp_path_factory.mktemp("hand-made"),
            immich,
            outbound_trap,
            notifications=_notifying(sink),
        )
        before = _suggested(home)
        result = home.run(
            "generate",
            "--from-album",
            ALBUMS[0]["albumName"],
            "--include-photos",
            "--no-music",
            "--quiet",
            "--upload-to-immich",
            scripted_selection=True,
        )
        yield _HandMade(home, result, sink.posted(), "uploaded-1", before, immich.base_url)
    sink.close()


@pytest.mark.feature("notifications.on-completion")
@pytest.mark.feature("notifications.upload-link")
@_UPLOADS_TO_ITS_OWN_FAKE
def test_generate_announces_its_uploaded_film_with_a_link_to_the_server(
    hand_made_album: _HandMade,
) -> None:
    assert hand_made_album.result.returncode == 0, hand_made_album.result.explain()
    messages = hand_made_album.messages
    assert [m["title"] for m in messages] == ["Memory Generated: Album"]
    # No public_url: the link starts from immich.url.
    link = f"Watch in Immich: {hand_made_album.immich_url}/photos/{hand_made_album.asset_id}"
    assert link in messages[0]["message"]


@pytest.mark.feature("automation.hand-made-counts")
@_UPLOADS_TO_ITS_OWN_FAKE
def test_an_album_filmed_by_hand_is_not_proposed_again(hand_made_album: _HandMade) -> None:
    assert hand_made_album.result.returncode == 0, hand_made_album.result.explain()
    lake_week = ALBUMS[0]["startDate"][:10] + " to " + ALBUMS[0]["endDate"][:10]

    after = _suggested(hand_made_album.home)

    assert lake_week in [
        r["date_range"] for r in hand_made_album.proposed_before if r["category"] == "album"
    ]
    assert [r for r in after if r["category"] == "album"] == []


# ── a saved cut ──────────────────────────────────────────────────────────


@pytest.mark.feature("notifications.on-completion")
def test_a_saved_cut_sends_nothing_until_runs_render_makes_its_film(
    tmp_path: Path, immich: LibraryServer, outbound_trap: OutboundTrap, sink: LocalHttp
) -> None:
    home = _home(tmp_path / "home", immich, outbound_trap, notifications=_notifying(sink))

    saved = home.run(*day_args(QUIET_DAY), "--no-render", scripted_selection=True)
    assert saved.returncode == 0, saved.explain()
    assert sink.posted() == []
    cut_id = re.findall(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})", saved.output)[0]

    rendered = home.run("runs", "render", cut_id, "--no-music")

    assert rendered.returncode == 0, rendered.explain()
    messages = sink.posted()
    assert len(messages) == 1 and messages[0]["title"].startswith("Memory Generated")
    assert "Output: " in messages[0]["message"]
