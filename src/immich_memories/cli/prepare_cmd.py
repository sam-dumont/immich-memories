"""Run preparation over a scope, say what it cost, and stop.

Preparation is the expensive half of a cut and it is banked per picture, so on a
low-power box it wants to be started a month at a time, overnight, and resumed --
not discovered by leaving a render running for four days.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from immich_memories.analysis.preparation_report import (
    ProducerClock,
    rate_report,
    total_seconds_per_picture,
)
from immich_memories.analysis.prepare_scope import eligible_source, run_preparation
from immich_memories.cli._helpers import (
    console,
    print_error,
    print_info,
    print_success,
    refuse_blocked_host,
)
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange
from immich_memories.tracking.run_observations import observed_command

if TYPE_CHECKING:
    from immich_memories.analysis.editorial_preparation import PreparationResult


def _windows(
    *, year: int | None, month: int | None, start: str | None, end: str | None, period: str | None
) -> list[DateRange]:
    from immich_memories.cli._date_resolution import resolve_date_range

    resolved = resolve_date_range(year, start, end, period, None, month=month)
    return list(resolved) if isinstance(resolved, list) else [resolved]


def _print_outcome(
    clock: ProducerClock, result: PreparationResult, *, pictures: int, library_size: int
) -> None:
    costs = clock.costs()
    for line in rate_report(
        costs,
        pictures=pictures,
        library_size=library_size,
        service_seconds=result.service_seconds_by_stage,
    ):
        console.print(line, highlight=False)
    if motion := result.transfer_by_stage.get("motion"):
        console.print(
            f"  motion lines: {motion['requests']:,} playback range requests, "
            f"{motion['bytes'] / 1e6:,.1f} MB read, {motion['seat_calls']:,} caption-seat calls",
            highlight=False,
        )
    if result.failures:
        print_error(f"{len(result.failures)} producer failures; the first few:")
        for key, detail in list(result.failures.items())[:5]:
            console.print(f"  {key}: {detail}", highlight=False)
    if excluded := result.unservable_sources:
        reasons = ", ".join(sorted(set(excluded.values())))
        print_info(f"{len(excluded):,} sources will leave any cut — {reasons}")
    optional = sum(
        len(ids) for key, ids in result.missing_by_producer.items() if key.startswith("motion:")
    )
    if optional:
        print_info(f"Motion unavailable for {optional} clips; cuts will use plain clip facts")
    required = {
        key: ids for key, ids in result.missing_by_producer.items() if not key.startswith("motion:")
    }
    if required:
        missing = ", ".join(f"{producer}: {len(ids)}" for producer, ids in required.items())
        print_error(f"Still missing after this pass — {missing}")
        return
    print_success(
        f"{pictures:,} pictures prepared at "
        f"{total_seconds_per_picture(costs, pictures):.4f} s/picture."
    )


def _bank_overviews(client, config: Config, scope, sources, unservable) -> None:
    """Bank the period accounts a later cut reads instead of paying for its own thesis."""
    from immich_memories.analysis.catalogue_runtime import catalogue_prepared_window
    from immich_memories.analysis.editorial_album_index import RunAlbumNames

    catalogue, unread = catalogue_prepared_window(
        sources,
        scope=scope,
        config=config,
        unservable=unservable,
        albums=RunAlbumNames(client),
        client=client,
    )
    print_success(
        f"Banked {len(catalogue.events):,} episode readings, "
        f"{len(catalogue.months):,} month and {len(catalogue.years):,} year account(s)."
    )
    if unread:
        print_info(f"{len(unread):,} episode(s) stayed unread; their months say less.")


def register_prepare_commands(cli_group: click.Group) -> None:
    """Register the preparation-only command on the main CLI group."""

    @cli_group.command()
    @click.option("--year", "-y", type=int, help="Calendar year to prepare")
    @click.option("--month", type=int, help="Month 1-12, with --year: one month at a time")
    @click.option("--start", type=str, help="Start date (YYYY-MM-DD)")
    @click.option("--end", type=str, help="End date (use with --start)")
    @click.option("--period", type=str, help="Period from the start date (e.g. 6m, 1y, 2w)")
    @click.option(
        "--overviews",
        is_flag=True,
        help="Also bank each month's episode readings and the account a cut reads as its thesis",
    )
    @click.option(
        "--library-size",
        type=int,
        default=1000,
        show_default=True,
        help="Project the measured rate onto a library of this many pictures",
    )
    @click.pass_context
    @observed_command("prepare")
    def prepare(
        ctx: click.Context,
        year: int | None,
        month: int | None,
        start: str | None,
        end: str | None,
        period: str | None,
        overviews: bool,
        library_size: int,
    ) -> None:
        """Prepare a scope's annotations, print what each producer cost, and stop.

        \b
        No selection and no render happen. Preparation is banked per picture, so
        a scope prepared today is free for every later cut:
          immich-memories prepare --year 2024 --month 6
          immich-memories prepare --start 2024-01-01 --period 1y
        \b
        --overviews goes one step further and banks what each month was about,
        which a cut of that month then reads instead of working it out again:
          immich-memories prepare --year 2024 --month 6 --overviews
        """
        from immich_memories.api.sync_client import SyncImmichClient

        config: Config = ctx.obj["config"]
        if not config.immich.url or not config.immich.api_key:
            print_error("Immich not configured. Run 'immich-memories config' first.")
            sys.exit(1)
        if overviews and config.editorial.resolve_reader(config.llm.model) == "rules":
            raise click.UsageError("--overviews needs a configured model reader")

        windows = _windows(year=year, month=month, start=start, end=end, period=period)
        refuse_blocked_host(config, output_directory=None)
        with SyncImmichClient(
            base_url=config.immich.url,
            api_key=config.immich.api_key,
            api_version=config.immich.api_version,
        ) as client:
            scope, sources, assets = eligible_source(client, config, windows)
            if not assets:
                print_info("No source-eligible pictures in that scope; nothing to prepare.")
                return
            print_info(f"Preparing {len(assets):,} pictures over {len(windows)} window(s)")
            clock, result = run_preparation(client, config, assets)
            if overviews and result.complete:
                _bank_overviews(client, config, scope, sources, result.unservable_sources)

        _print_outcome(clock, result, pictures=len(assets), library_size=library_size)
        if not result.complete:
            sys.exit(1)
