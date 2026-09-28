"""A pasteable report, kept local until the owner chooses to share it."""

from pathlib import Path

import click

from immich_memories.db import open_store
from immich_memories.tracking.report_service import report_for_run


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
    @click.pass_context
    def report(
        ctx: click.Context,
        run_id: str | None,
        as_json: bool,
        bundle: Path | None,
        include_flagged_captions: bool,
    ) -> None:
        """Print a privacy-safe GitHub issue report. Defaults to the latest run.

        Logs are included. Review the report before sharing it. Nothing is sent.
        """
        config = ctx.obj["config"]
        try:
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
