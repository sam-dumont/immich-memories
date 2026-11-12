"""`runs label`: write a delivered film's label to Immich again, without rendering it again."""

from __future__ import annotations

import sys

import click

from immich_memories.api.film_relabel import RelabelStatus
from immich_memories.cli._helpers import print_error, print_info, print_success, print_warning
from immich_memories.cli.runs_upload import immich_client

_WORDS = {
    RelabelStatus.WRITTEN: "written",
    RelabelStatus.UNCHANGED: "unchanged",
    RelabelStatus.ASSET_GONE: "asset gone from Immich",
    RelabelStatus.RIGHTS_MISSING: "rights missing",
    RelabelStatus.FAILED: "failed",
}


def _report(result) -> None:
    outcome = result.outcome
    line = f"{result.run_id}: {_WORDS[outcome.status]}"
    if outcome.detail:
        line += f" ({outcome.detail})"
    if outcome.removed:
        line += f"; removed {len(outcome.removed)} old tag(s): " + ", ".join(outcome.removed)
    if outcome.status is RelabelStatus.WRITTEN and not outcome.warnings:
        print_success(line, highlight=False)
    elif outcome.status is RelabelStatus.UNCHANGED:
        print_info(line)
    else:
        print_warning(line)
    for warning in outcome.warnings:
        print_warning(f"  {warning}")


def _failed(results, every_run: bool) -> bool:
    """Whether the exit code is 1: a key that cannot write, a write that failed or did not stay,
    or a named run whose film is gone. With `--all`, a film gone is a report, not a failure."""
    refused = {RelabelStatus.RIGHTS_MISSING, RelabelStatus.FAILED}
    if any(r.outcome.status in refused or r.outcome.warnings for r in results):
        return True
    return not every_run and results[0].outcome.status is RelabelStatus.ASSET_GONE


def register_label_command(runs: click.Group) -> None:
    """Add `runs label` to the `runs` group."""

    @runs.command("label")
    @click.argument("run_id", required=False)
    @click.option("--all", "every_run", is_flag=True, help="Re-label every run delivered to Immich")
    def runs_label(run_id: str | None, every_run: bool) -> None:
        """Write RUN_ID's description and tags to its film in Immich again.

        Nothing is rendered or uploaded: the label is rebuilt from the stored run and written to
        the asset the run was delivered as, by the same write-and-settle steps as the upload. The
        app's own tags the current label no longer has (version, generated-on, type, year, story)
        are removed; a tag outside those kinds is never touched. A film whose label already
        matches is left alone and reported as unchanged. A film gone from Immich, or a key without
        the tag and asset-update rights, is reported and nothing is written.

        Give a RUN_ID, or --all for every delivered run.
        """
        import httpx

        from immich_memories.api.immich import ImmichAPIError
        from immich_memories.config import get_config
        from immich_memories.operations.film_relabel import (
            RelabelRefused,
            relabel_all,
            relabel_run,
        )

        if bool(run_id) == every_run:
            print_error("Give a RUN_ID or --all, not both.")
            sys.exit(2)
        config = get_config()
        try:
            with immich_client(config) as client:
                results = (
                    relabel_all(config, client=client)
                    if every_run
                    else [relabel_run(config, str(run_id), client=client)]
                )
        except RelabelRefused as refusal:
            print_error(str(refusal))
            sys.exit(1)
        except (ImmichAPIError, httpx.HTTPError) as error:
            print_error(f"Immich could not take the label: {type(error).__name__}")
            sys.exit(1)
        for result in results:
            _report(result)
        if not results:
            print_info("No run was delivered to Immich, so there is nothing to re-label.")
        if _failed(results, every_run):
            sys.exit(1)
