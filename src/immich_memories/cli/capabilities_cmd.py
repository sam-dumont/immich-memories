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
    @click.option(
        "--verify-local",
        is_flag=True,
        help="Verify configured owned reader and cached local audio with synthetic inputs; no full-film certification",
    )
    @click.option("--json", "as_json", is_flag=True, help="Print the report as JSON")
    @click.pass_context
    def capabilities(
        ctx: click.Context, test_music: bool, verify_local: bool, as_json: bool
    ) -> None:
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

        if test_music and verify_local:
            raise click.UsageError(
                "Choose --test-music or --verify-local; the former may download models"
            )
        config = ctx.obj["config"]
        tier = str(config.tier)
        summary = {
            "basic": "Rules selection and CPU classifiers; films capped at 1080p",
            "gpu": "Rules selection with captions and Laya; rendering follows available hardware",
            "full": "LLM selection with captions and Laya; rendering follows available hardware",
        }.get(tier, "Automatic selection follows detected inference capability")
        # Legacy preflight can issue one-token external LLM requests. The explicit
        # local-only test keeps other health checks but never exercises that provider.
        preflight_config = config
        if verify_local and config.llm.base_url.strip():
            preflight_config = config.model_copy(deep=True)
            preflight_config.llm.enabled = False
        rows = [Capability(f"Selection tier: {tier}", "configured", summary)]
        rows.extend(
            Capability(
                check.name,
                f"check: {check.status.value}",
                "; ".join(filter(None, (check.message, check.details))),
            )
            for check in run_preflight_checks(preflight_config)
            # The switched-off copy would report "configured but disabled" for a reader the
            # config enables; the external reader is reported by the local-capability rows.
            if not (preflight_config is not config and check.name == "LLM")
        )
        rows.extend(optional_capabilities(config))
        rows.extend(music_capabilities(config, test_music=test_music))
        from immich_memories.local_capabilities import local_capabilities, verify_local_capabilities

        if verify_local:
            import asyncio

            rows.extend(asyncio.run(verify_local_capabilities(config)))
        else:
            rows.extend(local_capabilities(config))
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
