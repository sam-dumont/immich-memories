"""Versioned detector facts: inspect compatibility before changing a stored answer."""

import json

import click

from immich_memories.analysis.editorial_clip_frames import CLIP_FRAMES_HEAD, CLIP_FRAMES_VERSION
from immich_memories.cli._helpers import console
from immich_memories.db import open_store
from immich_memories.store.detector_cache import CONTRACT, fact_status, migrate_facts, refresh_facts


def register_fact_commands(group: click.Group) -> None:
    """Add detector fact maintenance to the existing store commands."""

    @group.group()
    def facts() -> None:
        """Inspect detector compatibility and plan selective refreshes."""

    @facts.command()
    @click.option(
        "--json", "as_json", is_flag=True, help="Print machine-readable compatibility counts"
    )
    @click.pass_context
    def status(ctx: click.Context, as_json: bool) -> None:
        """Show banked producer versions; an app upgrade alone does not invalidate them."""
        config = ctx.obj["config"]
        versions = dict(config.editorial.head_versions) | {CLIP_FRAMES_HEAD: CLIP_FRAMES_VERSION}
        rows = fact_status(open_store(config), versions)
        report = {"contract": CONTRACT, "rows": rows}
        if as_json:
            click.echo(json.dumps(report))
            return
        console.print(f"Detector cache contract: {CONTRACT}")
        for row in rows:
            console.print(f"{row['head']}@{row['version']}: {row['facts']} facts, {row['state']}")

    @facts.command()
    @click.option(
        "--apply", is_flag=True, help="Apply the compatible migration; default only reports it"
    )
    @click.option("--json", "as_json", is_flag=True, help="Print the migration report as JSON")
    @click.pass_context
    def migrate(ctx: click.Context, apply: bool, as_json: bool) -> None:
        """Carry compatible Marqo still facts forward without inference; keep old versions."""
        report = migrate_facts(open_store(ctx.obj["config"]), apply=apply)
        if as_json:
            click.echo(json.dumps(report))
            return
        console.print(
            f"{report['head']} {report['from']} -> {report['to']}: {report['eligible']} compatible facts"
        )
        console.print(
            "Applied; old facts retained."
            if apply
            else "Preview only. Use --apply to copy these facts."
        )
        for asset_id in report["asset_ids"]:
            console.print(asset_id, markup=False)

    @facts.command()
    @click.option(
        "--head",
        "heads",
        multiple=True,
        required=True,
        help="Detector to refresh; repeat for multiple heads",
    )
    @click.option(
        "--asset",
        "asset_ids",
        multiple=True,
        required=True,
        help="Asset ID to refresh; repeat for multiple assets",
    )
    @click.option(
        "--apply", is_flag=True, help="Forget the selected facts; default only reports them"
    )
    @click.option("--json", "as_json", is_flag=True, help="Print the selected refresh as JSON")
    @click.pass_context
    def refresh(
        ctx: click.Context,
        heads: tuple[str, ...],
        asset_ids: tuple[str, ...],
        apply: bool,
        as_json: bool,
    ) -> None:
        """Plan a selective detector refresh; --apply removes only those facts, all versions.

        Stop preparation workers first. Run prepare for the affected scope afterwards.
        Captions, pixel measurements, other detectors and owner decisions stay banked.
        """
        report = refresh_facts(
            open_store(ctx.obj["config"]), heads=heads, asset_ids=asset_ids, apply=apply
        )
        if as_json:
            click.echo(json.dumps(report))
            return
        console.print(f"{report['facts']} facts across {len(report['asset_ids'])} selected assets")
        console.print("Heads: " + ", ".join(report["heads"]), markup=False)
        for asset_id in report["asset_ids"]:
            console.print(asset_id, markup=False)
        console.print(
            "Selected facts removed. Run prepare for their scope to recompute."
            if apply
            else "Preview only. Use --apply to remove these facts."
        )
