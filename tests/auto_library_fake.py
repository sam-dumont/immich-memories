"""A small Immich library and a stand-in `generate` child, for automation feature tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, create_autospec, patch

from immich_memories.api.immich import SyncImmichClient
from immich_memories.api.models import TimeBucket
from immich_memories.automation.models import ProcessResult
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase


def fake_library(months: dict[str, int]) -> MagicMock:
    """An Immich client, autospecced from the real one, holding ``months`` of pictures."""
    client = create_autospec(SyncImmichClient, instance=True)
    client.__enter__.return_value = client
    client.get_time_buckets.return_value = [
        TimeBucket(count=count, timeBucket=f"{month}-01T00:00:00.000Z")
        for month, count in months.items()
    ]
    client.get_all_people.return_value = []
    client.get_albums.return_value = []
    client.count_assets_with_people.return_value = 0
    client.get_assets_for_date_range.return_value = []
    return client


def last_month(today: date | None = None) -> tuple[date, date]:
    """The first and last day of the month before ``today``."""
    first_this = (today or date.today()).replace(day=1)
    end = first_this - timedelta(days=1)
    return end.replace(day=1), end


def library_with_last_month() -> MagicMock:
    start, _ = last_month()
    return fake_library({f"{start:%Y-%m}": 80})


@contextmanager
def immich_serving(client: MagicMock) -> Iterator[None]:
    """Every Immich read and the preflight probe answer from ``client``."""
    from immich_memories.preflight import CheckStatus

    with (
        # WHY: the Immich server; the fake is built from the real client's signatures.
        patch("immich_memories.api.accounts.SyncImmichClient", return_value=client),
        # WHY: preflight's health probe is an HTTP call to the same server.
        patch(
            "immich_memories.preflight_immich.check_immich",
            return_value=MagicMock(status=CheckStatus.OK),
        ),
    ):
        yield


class FakeGenerateChild:
    """Stands in for the `generate` child: records its argv and records a finished film.

    Like the real child, it writes into the store of the config its command line names,
    or the default config's store when it names none.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> ProcessResult:
        self.commands.append(cmd)
        config = (
            Config.from_yaml(Path(cmd[cmd.index("--config") + 1]))
            if "--config" in cmd
            else Config()
        )
        flags = dict(arg[2:].split("=", 1) for arg in cmd if arg.startswith("--") and "=" in arg)
        film = self.output_dir / f"film-{len(self.commands)}.mp4"
        film.parent.mkdir(parents=True, exist_ok=True)
        film.write_bytes(b"film")
        now = datetime.now(tz=UTC)
        RunDatabase(open_store(config)).save_run(
            RunMetadata(
                run_id=f"child-run-{len(self.commands)}",
                created_at=now,
                completed_at=now,
                status="completed",
                source="auto",
                memory_type=cmd[cmd.index("--memory-type") + 1],
                memory_key=flags.get("memory-key"),
                memory_category=flags.get("memory-category"),
                automation_attempt_id=flags.get("automation-attempt-id"),
                output_path=str(film),
            )
        )
        return ProcessResult(returncode=0, stdout="", stderr="")


def load_config_file(tmp_path: Path, extra_yaml: str = "", **automation: object) -> Config:
    """Write a config file and load it as this process's config, as `--config` does."""
    from immich_memories.config_loader import load_config

    lines = "".join(f"    {key}: {value!r}\n" for key, value in automation.items())
    path = tmp_path / "config.yaml"
    path.write_text(
        "immich:\n  url: https://immich.example.test\n  api_key: test-key\n"
        f"cache:\n  database: {tmp_path / 'runs.db'}\n  directory: {tmp_path / 'cache'}\n"
        "advanced:\n  automation:\n    detect_trips: false\n" + lines + extra_yaml
    )
    return load_config(path)


def suggest_json(config: Config, client: MagicMock, today: date, *flags: str) -> list[dict]:
    """`auto suggest --json` as a user runs it, on ``today``, over ``client``."""
    import json

    return json.loads(suggest_output(config, client, today, "--json", *flags))


def suggest_output(config: Config, client: MagicMock, today: date, *flags: str) -> str:
    """What `auto suggest` prints, on ``today``, over ``client``."""
    from click.testing import CliRunner

    from immich_memories.cli import auto_cmd

    class _Today(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return today

    with (
        immich_serving(client),
        # WHY: the wall clock; these behaviours live on particular days of the year.
        patch("immich_memories.automation.candidate_discovery.date", _Today),
    ):
        result = CliRunner().invoke(
            auto_cmd.auto, ["suggest", *flags], obj={"config": config, "config_path": None}
        )
    assert result.exit_code == 0, result.output
    return result.output


class FakeApprise:
    """Apprise as the notifier sees it: `notify` is False when any added URL failed.

    Install with `install_fake_apprise`; `delivered` collects (url, title) per delivery.
    """

    delivered: list[tuple[str, str]] = []
    dead: frozenset[str] = frozenset()
    instantiate: object = None

    def __init__(self) -> None:
        self.urls: list[str] = []

    def add(self, url: str) -> bool:
        self.urls.append(url)
        return True

    def notify(self, title: str, body: str, **_kwargs: object) -> bool:
        for url in self.urls:
            if url not in self.dead:
                type(self).delivered.append((url, title))
        return not any(url in self.dead for url in self.urls)


def install_fake_apprise(monkeypatch, dead: frozenset[str] = frozenset()) -> type[FakeApprise]:
    import apprise as real

    FakeApprise.delivered = []
    FakeApprise.dead = dead
    # Config validation parses the URLs through Apprise's own parser; that stays real.
    FakeApprise.instantiate = staticmethod(real.Apprise.instantiate)
    # WHY: the notification providers; this stand-in keeps Apprise's all-or-nothing answer.
    monkeypatch.setattr(real, "Apprise", FakeApprise)
    return FakeApprise
