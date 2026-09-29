"""A pasteable report, kept local until the owner chooses to share it."""

from pathlib import Path

import click

from immich_memories.db import open_store
from immich_memories.tracking.report_service import report_for_run


def mark_run(store, config, run_id: str, *, wrong: tuple[str, ...], missing: str) -> None:
    """Keep the owner's marks on a free-text run, checked against its translation."""
    from immich_memories.free_text.library import read_library
    from immich_memories.free_text.marks import marked
    from immich_memories.tracking.span_store import SpanStore

    spans = SpanStore(store)
    record = spans.diagnostics(run_id).get("free_text")
    if record is None:
        raise LookupError(f"Run {run_id} is not a free-text run: nothing to mark")
    pool = record.get("marks_basis", {}).get("pool", [])
    captions = [p.caption for p in read_library(store, config.editorial, asset_ids=pool).pictures]
    spans.amend(
        run_id, free_text=marked(record, wrong=wrong, missing=missing, pool_captions=captions)
    )


def register_report_commands(main: click.Group) -> None:
    """Expose the shared builder through Markdown, JSON and ZIP outputs."""

    @main.command("report")
    @click.argument("run_id", required=False)
    @click.option("--json", "as_json", is_flag=True, help="Print the redacted report as JSON")
    @click.option(
        "--bundle",
        type=click.Path(path_type=Path, dir_okay=False),
        help="Write the full redacted report to a ZIP file",
    )
    @click.option(
        "--include-flagged-captions",
        is_flag=True,
        help="Include captions and reasons of flagged free-text photos; review before sharing",
    )
    @click.option(
        "--wrong",
        multiple=True,
        metavar="ASSET_ID",
        help="Mark a photo of a free-text film as wrong (repeatable); kept on the run",
    )
    @click.option(
        "--missing",
        metavar="TEXT",
        help="Say what a free-text film is missing; kept on the run and checked against it",
    )
    @click.pass_context
    def report(
        ctx: click.Context,
        run_id: str | None,
        as_json: bool,
        bundle: Path | None,
        include_flagged_captions: bool,
        wrong: tuple[str, ...],
        missing: str | None,
    ) -> None:
        """Print a privacy-safe GitHub issue report. Defaults to the latest run.

        Logs are included. Review the report before sharing it. Nothing is sent.
        """
        config = ctx.obj["config"]
        try:
            if wrong or missing:
                if run_id is None:
                    raise ValueError("--wrong and --missing need the run's id")
                mark_run(open_store(config), config, run_id, wrong=wrong, missing=missing or "")
            built = report_for_run(
                open_store(config),
                config,
                run_id,
                include_flagged_captions=include_flagged_captions,
            )
            if bundle is not None:
                bundle.write_bytes(built.bundle())
        except (LookupError, ValueError, OSError) as error:
            raise click.ClickException(str(error)) from error
        click.echo(built.json() if as_json else built.markdown(), nl=False)
