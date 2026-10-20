"""The `version` command, and its opt-in check for a newer release."""

from __future__ import annotations

import click


def register_version_command(main: click.Group) -> None:
    """Add `version`, which only calls out when asked with --check."""

    @main.command("version")
    @click.option(
        "--check",
        is_flag=True,
        help="Ask GitHub whether a newer release is out. One anonymous request; "
        "nothing about this install is sent",
    )
    def version(check: bool) -> None:
        """Print the running version, and with --check say whether a newer release is out."""
        from immich_memories import update_check

        click.echo(f"immich-memories {update_check.__version__}")
        if not check:
            return
        status = update_check.check_now()
        if status.status == "failed":
            click.echo(f"Could not check for updates: {status.reason}.", err=True)
            raise SystemExit(1)
        if status.status == "current":
            click.echo("You're up to date.")
            return
        click.echo(f"{status.latest} is out. Release notes: {status.notes_url}")
        if status.command:
            click.echo(f"Update: {status.command}")
        else:
            click.echo(f"Upgrading: {status.docs_url}")
