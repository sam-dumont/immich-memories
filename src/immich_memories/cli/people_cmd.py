"""Reading the library's people graph, and writing it down."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import click

from immich_memories.cli._helpers import console, print_error, print_success
from immich_memories.db import open_store
from immich_memories.people.account_ids import entry_ids, ids_by_account
from immich_memories.people.companion import (
    bind_alias,
    load_document,
    people_entries,
    retained_immich_ids,
    save_graph,
)
from immich_memories.people.evidence_graph import (
    default_evidence_graph_path,
    save_evidence_graph,
)
from immich_memories.people.graph import DEFAULT_MIN_ASSETS, PeopleGraph
from immich_memories.people.signatures import LinkKind

_TIER_ORDER = ("inner", "recurring", "episodic", "event")

_HOW_THE_OWNER_WAS_FOUND = {
    "told": "you said so",
    "account": "matched the Immich account name",
    "inferred": "inferred — longest span, most pictures",
}


def register_people_commands(cli_group: click.Group) -> None:
    """Register the people commands on the main CLI group."""

    @click.group("people", invoke_without_command=True)
    @click.pass_context
    def people(ctx: click.Context) -> None:
        """Who is in this library, and who they are to each other.

        Called on its own this still lists the people Immich knows, which is
        what `immich-memories people` has always done.
        """
        if ctx.invoked_subcommand is None:
            _list_immich_people(ctx.obj["config"])

    _register_scan(people)
    _register_show(people)
    _register_transfer(people)
    _register_bind(people)
    cli_group.add_command(people)


def _list_immich_people(config: Any) -> None:
    """Every named person Immich holds, which is what `--person` matches on."""
    import sys

    from rich.table import Table

    from immich_memories.api.sync_client import SyncImmichClient

    if not config.immich.url or not config.immich.api_key:
        print_error("Immich not configured. Run 'immich-memories config' first.")
        sys.exit(1)

    with SyncImmichClient(
        base_url=config.immich.url,
        api_key=config.immich.api_key,
        api_version=config.immich.api_version,
    ) as client:
        found = client.get_all_people()

    table = Table(title="People in Immich")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    for person in sorted(found, key=lambda p: p.name):
        if person.name:
            table.add_row(person.name, person.id[:8] + "...")

    console.print(table)
    console.print(f"\nTotal: {len([p for p in found if p.name])} named people")


def _register_scan(people: click.Group) -> None:
    @people.command("scan")
    @click.option(
        "--min-assets",
        type=int,
        default=DEFAULT_MIN_ASSETS,
        help="Pictures a named person needs before the graph has an opinion",
    )
    @click.option(
        "--owner",
        envvar="IMMICH_MEMORIES_OWNER",
        default=None,
        help="The name of the person whose library this is, if the account does not say",
    )
    def scan(min_assets: int, owner: str | None) -> None:
        """Build or refresh the people registry from Immich.

        Reads every named person's count and month curve, then asks about each
        remaining pair to find who appears with whom. Nothing here looks at a
        pixel and nothing here asks you a question: the library's own
        distribution is the whole input.

        Safe to re-run: everything you confirmed is copied through untouched,
        and preferred to this pass's reading forever after.
        """
        from immich_memories.api.sync_client import SyncImmichClient
        from immich_memories.config import get_config
        from immich_memories.people.graph import build_graph

        config = get_config()
        store = open_store(config)
        graph_path = default_evidence_graph_path()
        retained = retained_immich_ids(load_document(store))
        with SyncImmichClient(base_url=config.immich.url, api_key=config.immich.api_key) as client:
            graph = build_graph(
                client,
                min_assets=min_assets,
                owner_name=owner,
                include_person_ids=retained,
            )

        save_graph(store, graph)
        save_evidence_graph(graph_path, graph, load_document(store))
        _report(graph)
        print_success(f"{len(graph.people)} people in the store ({store.location})")
        print_success(f"{len(graph.cooccurrences)} measured connections in {graph_path}")


def _register_show(people: click.Group) -> None:
    @people.command("show")
    @click.option(
        "--tier",
        type=click.Choice(_TIER_ORDER),
        default=None,
        help="Show only one tier",
    )
    def show(tier: str | None) -> None:
        """Print the people registry: what the last scan read and what you confirmed."""
        store = open_store()
        document = load_document(store)
        entries = people_entries(document)
        if not entries:
            console.print(
                "[yellow]No people in the store yet — run 'immich-memories people scan'.[/yellow]"
            )
            return

        _print_owner(document.get("owner"))
        for entry in _sorted(entries):
            if tier and _tier_of(entry) != tier:
                continue
            console.print(_person_line(entry))
        console.print(f"[dim]{store.location}[/dim]")


def _register_transfer(people: click.Group) -> None:
    @people.command("export")
    @click.option(
        "--to",
        "target",
        type=click.Path(dir_okay=False, path_type=Path),
        default=None,
        help="Write the YAML here instead of to standard output",
    )
    def export(target: Path | None) -> None:
        """Write the people registry out as YAML, in the shape people.yaml had.

        The file holds names and birth dates, so it is created readable by you
        alone. Edit it and bring it back with `people import`.
        """
        from immich_memories.people.transfer import export_yaml
        from immich_memories.security import write_secret_file

        text = export_yaml(open_store())
        if target is None:
            click.echo(text, nl=False)
            return
        write_secret_file(target, text)
        print_success(f"People registry written to {target}")

    @people.command("import")
    @click.option(
        "--from",
        "source",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        required=True,
        help="A YAML file written by `people export` (or an old people.yaml)",
    )
    @click.option(
        "--replace",
        is_flag=True,
        help="Overwrite a registry that already holds people",
    )
    def import_(source: Path, replace: bool) -> None:
        """Replace the people registry with a YAML file, keeping every id as written.

        The whole file is checked first; if any person in it is malformed,
        nothing is written and every problem is listed. A registry that already
        holds people is only overwritten with --replace.
        """
        import sys

        from immich_memories.people.transfer import (
            PeopleImportError,
            import_document,
            parse_yaml,
        )

        try:
            count = import_document(open_store(), parse_yaml(source.read_text()), replace=replace)
        except PeopleImportError as exc:
            print_error(f"{source} was not imported; nothing changed:")
            for problem in exc.problems:
                console.print(f"  {problem}")
            sys.exit(1)
        print_success(f"{count} people imported from {source}")


def _register_bind(people: click.Group) -> None:
    @people.command("bind")
    @click.argument("person")
    @click.option(
        "--account",
        required=True,
        help="The account that reads the id: primary, or an extra account's name",
    )
    @click.option(
        "--id",
        "alias_id",
        required=True,
        help="The person's id as that account's Immich knows them",
    )
    def bind(person: str, account: str, alias_id: str) -> None:
        """Say that one person has this id in another Immich account.

        PERSON is a store person id or a name exactly one person carries. The
        binding only adds the id: the name, birth date and everything you
        confirmed stay as they are. An id somebody else holds is refused,
        never merged, and binding the same id again changes nothing.
        """
        import sys

        store = open_store()
        try:
            entry = _person_named(people_entries(load_document(store)), person)
            if alias_id in ids_by_account(entry).get(account, []):
                console.print(f"{alias_id} is already bound to {_who(entry)}; nothing changed.")
                return
            bind_alias(store, entry_ids(entry)[0], alias_id, account=account)
        except ValueError as exc:
            print_error(str(exc))
            sys.exit(1)
        print_success(f"Bound {alias_id} ({account} account) to {_who(entry)}")


def _person_named(entries: list[dict[str, Any]], person: str) -> dict[str, Any]:
    """The one entry `person` names: an id it holds first, then an exact name."""

    held = [entry for entry in entries if person in entry_ids(entry)]
    if held:
        return held[0]
    named = [entry for entry in entries if entry.get("name") == person]
    if len(named) == 1:
        return named[0]
    if named:
        listed = ", ".join(entry_ids(entry)[0] for entry in named)
        raise ValueError(f"{len(named)} people are named {person!r} ({listed}); pass a person id")
    raise ValueError(f"No person with the id or name {person!r}; `people show` lists them")


def _who(entry: dict[str, Any]) -> str:

    return f"{entry.get('name') or '?'} ({entry_ids(entry)[0]})"


def _report(graph: PeopleGraph) -> None:
    """A summary of what the scan read, deliberately without the roster.

    A real library's inner circle is the user's household by name. Printing
    every one of them to a terminal that may be a log, a screenshot or a
    shared session is not something a scan should do on its own; `people show`
    asks for it on purpose.
    """
    if graph.owner is not None:
        _print_owner(
            {"name": graph.owner.name, "identified": graph.owner.identified},
        )

    counted = _tier_counts(node.tier.value for node in graph.people)
    for name in _TIER_ORDER:
        console.print(f"  [bold]{name:<10}[/bold] {counted.get(name, 0):>4}")

    flags = _flag_counts(graph)
    if flags:
        console.print(f"  [yellow]{flags}[/yellow]")


def _flag_counts(graph: PeopleGraph) -> str:
    twins = _people_with(graph, LinkKind.TWIN)
    duplicates = _people_with(graph, LinkKind.DUPLICATE)
    said = []
    if twins:
        said.append(f"{twins // 2} twin pair(s) — their counts are not to be trusted")
    if duplicates:
        said.append(f"{duplicates // 2} name(s) on two person records — merge them in Immich")
    return "; ".join(said)


def _people_with(graph: PeopleGraph, kind: LinkKind) -> int:
    return sum(1 for node in graph.people for link in node.links if link.kind is kind)


def _tier_counts(tiers: Iterable[str]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for tier in tiers:
        counted[tier] = counted.get(tier, 0) + 1
    return counted


def _print_owner(owner: dict[str, Any] | None) -> None:
    if not owner:
        console.print("[yellow]No owner identified — pass --owner to name them.[/yellow]")
        return
    how = _HOW_THE_OWNER_WAS_FOUND.get(str(owner.get("identified")), "unknown")
    console.print(f"  owner: [bold]{owner.get('name')}[/bold] [dim]({how})[/dim]")


def _sorted(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda entry: (
            _TIER_ORDER.index(_tier_of(entry))
            if _tier_of(entry) in _TIER_ORDER
            else len(_TIER_ORDER),
            -_evidence_of(entry).get("count", 0),
        ),
    )


def _person_line(entry: dict[str, Any]) -> str:
    evidence = _evidence_of(entry)
    confirmed = entry.get("confirmed") or {}
    role = confirmed.get("role")
    line = (
        f"  [bold]{entry.get('name', '?'):<24}[/bold] {_tier_of(entry):<10}"
        f" {evidence.get('count', 0):>6} pics"
        f"  {evidence.get('active_months', 0):>4} months"
        f"  [dim]since {evidence.get('onset') or evidence.get('first_month') or '?'}[/dim]"
    )
    for era, share in (evidence.get("era_day_share") or {}).items():
        line += f"  [dim]{era} {share:.0%}[/dim]"
    return f"{line}  [green]{role}[/green]" if role else line


def _tier_of(entry: dict[str, Any]) -> str:
    inferred = entry.get("inferred")
    return str(inferred.get("tier", "")) if isinstance(inferred, dict) else ""


def _evidence_of(entry: dict[str, Any]) -> dict[str, Any]:
    inferred = entry.get("inferred")
    evidence = inferred.get("evidence") if isinstance(inferred, dict) else None
    return evidence if isinstance(evidence, dict) else {}
