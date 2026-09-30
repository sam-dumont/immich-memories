"""Describe the configured setup and optionally prove smaller local music profiles."""

from __future__ import annotations

import json
from dataclasses import asdict

import click
from rich.table import Table

from immich_memories.cli._helpers import console


def register_capabilities_command(main: click.Group) -> None:
    """Add one setup report backed by the same checks the app already uses."""

    @main.command("capabilities")
    @click.option(
        "--test-music",
        is_flag=True,
        help="Generate 15 seconds for each local ACE-Step profile that fits; may download models.",
    )
    @click.option("--json", "as_json", is_flag=True, help="Print the report as JSON")
    @click.pass_context
    def capabilities(ctx: click.Context, test_music: bool, as_json: bool) -> None:
        """Show what this setup supports, what is missing, and which music profiles work.

        Connection and installation checks are labelled separately from real generation.
        Saved settings and running model servers are left alone. Use --test-music after
        unloading idle models if you want to test music with their memory freed.
        """
        from immich_memories.preflight import run_preflight_checks
        from immich_memories.setup_capabilities import (
            Capability,
            music_capabilities,
            optional_capabilities,
        )

        config = ctx.obj["config"]
        tier = str(config.tier)
        summary = {
            "nas": "Rules selection and CPU classifiers; films capped at 1080p",
            "gpu": "Rules selection with captions and Laya; rendering follows available hardware",
            "full": "LLM selection with captions and Laya; rendering follows available hardware",
        }.get(tier, "Automatic selection follows detected inference capability")
        rows = [Capability(f"Selection tier: {tier}", "configured", summary)]
        rows.extend(
            Capability(
                check.name,
                f"check: {check.status.value}",
                "; ".join(filter(None, (check.message, check.details))),
            )
            for check in run_preflight_checks(config)
        )
        rows.extend(optional_capabilities(config))
        rows.extend(music_capabilities(config, test_music=test_music))
        note = (
            "Checks prove connection, installation or a hardware probe, not a complete film. "
            "Verified music means real local generation. Memory estimates cover weights only; "
            "longer tracks and concurrent services can need more."
        )
        if as_json:
            click.echo(json.dumps({"capabilities": [asdict(row) for row in rows], "note": note}))
            return
        table = Table(title="This setup")
        for heading in ("Capability", "Evidence", "Result / next step"):
            table.add_column(heading)
        for row in rows:
            from rich.text import Text

            table.add_row(Text(row.name), Text(row.status), Text(row.message))
        console.print(table)
        console.print(note)
