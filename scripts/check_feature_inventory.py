#!/usr/bin/env python3
"""Fail when an advertised feature has no feature test and no stated reason.

`tests/features/inventory.yaml` lists every feature the README and the docs site
promise. Each row either names the feature tests that check it or carries a status.
A test is one of:

* a pytest node id (``tests/.../test_x.py::test_y``) marked
  ``@pytest.mark.feature("<row id>")``. The browser suite is pytest too: a Playwright
  test is a ``tests/e2e/`` node id, marked the same way, in a file ``make e2e`` runs;
* a Node test (``docs-site/.../x.test.mjs::<title>``), the ``test()`` title as written in
  the source (a template literal keeps its ``${...}``), with a ``// feature: <row id>``
  comment on the line above the ``test(`` call, in a file a Makefile ``node --test``
  line runs.

The statuses are:

* ``lane_only: <reason>``: only real hardware, an OS service or a cluster shows it;
* ``gap: #<issue>``: not covered yet. The number of gap rows is a ratchet: it may fall,
  and rises only by raising ``gap_ceiling`` in the same commit.

The check fails when:

a. a CLI command or flag (the Click tree `make docs-cli` documents), an offered memory
   type or an automation detector has no row covering it;
b. a row's tests do not collect, or do not carry its ``feature`` marker, or a marked
   test names no row, or a listed test sits in a file no CI target runs;
c. a row is malformed (id, promise, doc page and anchor, one of tests or status), or
   the gap rows outnumber ``gap_ceiling``.

Usage: ``uv run python scripts/check_feature_inventory.py`` (``make feature-check``).
"""

from __future__ import annotations

import ast
import contextlib
import io
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import yaml

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tests" / "features" / "inventory.yaml"
DOCS = ROOT / "docs-site" / "docs"
AUTOMATION = ROOT / "src" / "immich_memories" / "automation"
# Folders whose feature-marked tests the check collects even when no row names them,
# so a marker pointing at a missing row is caught.
FEATURE_TEST_ROOTS = (
    "tests/features",
    "tests/integration/features",
    "tests/integration/immich_gate",
    "tests/e2e",
)
# Folders whose Node tests the check reads for `// feature:` comments, for the same reason.
NODE_TEST_ROOTS = ("docs-site/src", "docs-site/scripts")
NODE_TEST_SUFFIXES = (".test.mjs", ".test.js", ".test.mts", ".test.ts")
E2E_ROOT = "tests/e2e/"
MAKEFILE = ROOT / "Makefile"

ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[.\-_][a-z0-9]+)*$")
STATUS_PATTERN = re.compile(r"^(?:lane_only: \S.*|gap: #\d+)$")
GAP_PATTERN = re.compile(r"^gap: #(\d+)$")


@dataclass(frozen=True, slots=True)
class Row:
    """One advertised feature."""

    id: str
    promise: str
    doc: str
    covers: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    status: str = ""

    @property
    def is_gap(self) -> bool:
        return bool(GAP_PATTERN.match(self.status))


@dataclass(slots=True)
class Inventory:
    rows: list[Row]
    gap_ceiling: int
    errors: list[str] = field(default_factory=list)


def load_inventory(text: str) -> Inventory:
    """Parse the YAML; shape errors are returned, not raised, so all of them print at once."""
    data = yaml.safe_load(text) or {}
    errors: list[str] = []
    ceiling = data.get("gap_ceiling")
    if not isinstance(ceiling, int) or ceiling < 0:
        errors.append("gap_ceiling must be a non-negative integer")
        ceiling = 0
    rows: list[Row] = []
    for index, raw in enumerate(data.get("features") or []):
        row, problems = _row(raw, index)
        errors.extend(problems)
        if row is not None:
            rows.append(row)
    return Inventory(rows=rows, gap_ceiling=ceiling, errors=errors)


def _row(raw: Any, index: int) -> tuple[Row | None, list[str]]:
    if not isinstance(raw, Mapping):
        return None, [f"features[{index}] is not a mapping"]
    row_id = str(raw.get("id") or f"features[{index}]")
    problems = []
    unknown = set(raw) - {"id", "promise", "doc", "covers", "tests", "status"}
    if unknown:
        problems.append(f"{row_id}: unknown keys {sorted(unknown)}")
    if not ID_PATTERN.match(row_id):
        problems.append(f"{row_id}: id must match {ID_PATTERN.pattern}")
    for key in ("promise", "doc"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            problems.append(f"{row_id}: {key} is required")
    tests = raw.get("tests")
    status = raw.get("status")
    if tests is not None and not (
        isinstance(tests, list) and all(isinstance(t, str) for t in tests)
    ):
        problems.append(f"{row_id}: tests must be a list of test ids")
        tests = None
    if status is not None and not (isinstance(status, str) and STATUS_PATTERN.match(status)):
        problems.append(f"{row_id}: status must be 'lane_only: <reason>' or 'gap: #<issue>'")
        status = None
    if not tests and not status:
        problems.append(f"{row_id}: needs feature tests or a lane_only/gap status")
    if tests and status and not GAP_PATTERN.match(status):
        # A known-broken feature may list its xfail test beside its gap; lane_only may not.
        problems.append(f"{row_id}: a row with tests may only carry a gap status")
    covers = raw.get("covers") or []
    if not isinstance(covers, list) or not all(isinstance(c, str) for c in covers):
        problems.append(f"{row_id}: covers must be a list of strings")
        covers = []
    row = Row(
        id=row_id,
        promise=str(raw.get("promise") or ""),
        doc=str(raw.get("doc") or ""),
        covers=tuple(covers),
        tests=tuple(tests or ()),
        status=str(status or ""),
    )
    return row, problems


# ── (a) what the product advertises ──────────────────────────────────────────


def cli_surfaces(root: click.Group) -> set[str]:
    """Every non-hidden command and option, as `cli:<path>` and `cli:<path> <first opt>`."""
    found: set[str] = set()
    found.update(_option_surfaces(root, ""))

    def walk(group: click.Group, prefix: str) -> None:
        for name, command in group.commands.items():
            if command.hidden:
                continue
            path = f"{prefix} {name}".strip()
            found.add(f"cli:{path}")
            found.update(_option_surfaces(command, path))
            if isinstance(command, click.Group):
                walk(command, path)

    walk(root, "")
    return found


def _option_surfaces(command: click.Command, path: str) -> set[str]:
    prefix = f"cli:{path} " if path else "cli:"
    return {
        f"{prefix}{param.opts[0]}"
        for param in command.params
        if isinstance(param, click.Option) and not param.hidden
    }


def memory_type_surfaces(offered: Iterable[str]) -> set[str]:
    return {f"memory-type:{value}" for value in offered}


def detector_surfaces(automation_dir: Path) -> set[str]:
    """Every `*Detector` class the automation package defines, read from source."""
    names: set[str] = set()
    for path in sorted(automation_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names.update(
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name.endswith("Detector")
        )
    return {f"detector:{name}" for name in names}


def uncovered(required: set[str], rows: Sequence[Row]) -> list[str]:
    covered = {surface for row in rows for surface in row.covers}
    return sorted(required - covered)


# ── (c) rows themselves ──────────────────────────────────────────────────────


def heading_anchors(markdown: str) -> set[str]:
    """Docusaurus heading ids: an explicit `{#id}`, else the slug of the heading text."""
    anchors: set[str] = set()
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        match = re.match(r"^#{1,6}\s+(.*?)\s*$", line)
        if in_fence or not match:
            continue
        text = match.group(1)
        explicit = re.search(r"\{#([^}]+)\}\s*$", text)
        anchors.add(explicit.group(1) if explicit else slug(text))
    return anchors


def slug(text: str) -> str:
    """github-slugger, which Docusaurus uses: lowercase, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def doc_errors(rows: Sequence[Row], docs_root: Path, readme: Path) -> list[str]:
    errors = []
    anchors_of: dict[Path, set[str]] = {}
    for row in rows:
        page, _, anchor = row.doc.partition("#")
        path = readme if page == "README.md" else docs_root / page
        if not path.is_file():
            errors.append(f"{row.id}: doc page {page!r} does not exist")
            continue
        if not anchor:
            continue
        if path not in anchors_of:
            anchors_of[path] = heading_anchors(path.read_text(encoding="utf-8"))
        if anchor not in anchors_of[path]:
            errors.append(f"{row.id}: {page} has no heading #{anchor}")
    return errors


def duplicate_ids(rows: Sequence[Row]) -> list[str]:
    seen: set[str] = set()
    duplicates = []
    for row in rows:
        if row.id in seen:
            duplicates.append(f"{row.id}: duplicate id")
        seen.add(row.id)
    return duplicates


def gap_ratchet(rows: Sequence[Row], ceiling: int) -> tuple[list[str], str]:
    """Errors when gaps outnumber the ceiling; a note when the ceiling can come down."""
    gaps = sum(row.is_gap for row in rows)
    if gaps > ceiling:
        return [
            f"{gaps} gap rows, ceiling {ceiling}: cover a feature instead, or raise "
            "gap_ceiling in the same commit and say why"
        ], ""
    note = (
        f"gap rows {gaps} < ceiling {ceiling}: lower gap_ceiling to {gaps}"
        if gaps < ceiling
        else ""
    )
    return [], note


# ── (b) rows against the collected tests ─────────────────────────────────────


def link_errors(rows: Sequence[Row], collected: Mapping[str, Sequence[str]]) -> list[str]:
    """Each listed node collects and is marked for its row; each marked test names a row.

    ``collected`` maps every collected node id to the ids its ``feature`` markers name.
    """
    errors = []
    known = {row.id for row in rows}
    listed: dict[str, set[str]] = {}
    for row in rows:
        for node in row.tests:
            listed.setdefault(node, set()).add(row.id)
            if node not in collected:
                errors.append(f"{row.id}: test {node} does not collect")
            elif row.id not in collected[node]:
                errors.append(f"{row.id}: test {node} lacks {_marker(node, row.id)}")
    for node, ids in sorted(collected.items()):
        for feature_id in ids:
            if feature_id not in known:
                errors.append(f"{node}: marked feature({feature_id!r}), which no row has")
            elif feature_id not in listed.get(node, set()):
                errors.append(f"{feature_id}: marked test {node} is not listed in its row")
    return errors


def _marker(node: str, feature_id: str) -> str:
    if is_node_test(node):
        return f"a '// feature: {feature_id}' comment above its test()"
    return f"@pytest.mark.feature({feature_id!r})"


def is_node_test(node: str) -> bool:
    return node.split("::", 1)[0].endswith(NODE_TEST_SUFFIXES)


# A `test(` or `it(` call opening with a quoted title, at the start of a line.
_NODE_TEST_CALL = re.compile(r"^\s*(?:test|it)\(\s*(['\"`])((?:\\.|(?!\1).)*)\1")
_FEATURE_COMMENT = re.compile(r"^\s*//\s*feature:\s*(\S+)\s*$")


def node_test_features(source: str) -> dict[str, list[str]]:
    """Each Node test title in a file, with the ids its `// feature:` comments name.

    The comments sit on the lines right above the `test(` call; a blank line or code
    between them ends the block.
    """
    found: dict[str, list[str]] = {}
    pending: list[str] = []
    for line in source.splitlines():
        if comment := _FEATURE_COMMENT.match(line):
            pending.append(comment.group(1))
            continue
        if call := _NODE_TEST_CALL.match(line):
            ids = found.setdefault(call.group(2), [])
            ids.extend(i for i in pending if i not in ids)
        if not line.lstrip().startswith("//"):
            pending = []
    return found


def collect_node_tests(rows: Sequence[Row], root: Path = ROOT) -> dict[str, list[str]]:
    """Every Node test the rows name or the Node test folders hold, as `path::title`."""
    files = {node.split("::", 1)[0] for row in rows for node in row.tests if is_node_test(node)}
    for folder in NODE_TEST_ROOTS:
        files.update(
            str(path.relative_to(root))
            for suffix in NODE_TEST_SUFFIXES
            for path in (root / folder).rglob(f"*{suffix}")
            if "node_modules" not in path.parts
        )
    collected: dict[str, list[str]] = {}
    for name in sorted(files):
        path = root / name
        if path.is_file():
            for title, ids in node_test_features(path.read_text(encoding="utf-8")).items():
                collected[f"{name}::{title}"] = ids
    return collected


def unrun_test_errors(rows: Sequence[Row], makefile: str) -> list[str]:
    """A listed browser or Node test in a file no CI target runs proves nothing.

    The pytest feature folders run under `make test-features` and the unit suite;
    `tests/e2e/` runs only the files the `e2e` target names, and Node tests only the
    files a `node --test` recipe line names.
    """
    e2e_files = set(re.findall(r"tests/e2e/[\w/]+\.py", _recipe(makefile, "e2e")))
    node_lines = [line for line in makefile.splitlines() if "--test" in line and "node" in line]
    errors = []
    for row in rows:
        for node in row.tests:
            path = node.split("::", 1)[0]
            if path.startswith(E2E_ROOT) and path not in e2e_files:
                errors.append(f"{row.id}: {path} is not in `make e2e`, so {node} never runs")
            elif is_node_test(path) and not any(
                path.endswith(word)
                for line in node_lines
                for word in line.split()
                if word.endswith(NODE_TEST_SUFFIXES)
            ):
                errors.append(f"{row.id}: no Makefile `node --test` line runs {path}")
    return errors


def _recipe(makefile: str, target: str) -> str:
    """The lines of one Makefile target's recipe."""
    match = re.search(rf"^{re.escape(target)}:.*?\n((?:\t.*\n?)*)", makefile, re.M)
    return match.group(1) if match else ""


class _FeatureCollector:
    """A pytest plugin that records each collected item's `feature` marker ids."""

    def __init__(self) -> None:
        self.items: dict[str, list[str]] = {}

    def pytest_collection_finish(self, session: Any) -> None:
        for item in session.items:
            # A row names the test function; its parametrized cases count as that one test.
            ids = self.items.setdefault(item.nodeid.split("[", 1)[0], [])
            for marker in item.iter_markers("feature"):
                ids.extend(str(arg) for arg in marker.args if str(arg) not in ids)


def collect_feature_tests(rows: Sequence[Row]) -> tuple[dict[str, list[str]], list[str]]:
    """Collect (never run) the files the rows name plus the feature test folders."""
    import pytest

    files = {node.split("::", 1)[0] for row in rows for node in row.tests if not is_node_test(node)}
    targets = sorted(
        {f for f in files if (ROOT / f).exists()}
        | {root for root in FEATURE_TEST_ROOTS if (ROOT / root).exists()}
    )
    collector = _FeatureCollector()
    printed = io.StringIO()
    # WHY addopts cleared: the default `-m` deselects integration tests, which include the
    # real-Immich gate's feature tests. Collection imports them; nothing runs.
    with contextlib.redirect_stdout(printed):
        code = pytest.main(
            ["--collect-only", "-q", "-p", "no:cacheprovider", "-o", "addopts=", *targets],
            plugins=[collector],
        )
    if code in (0, 5):
        return collector.items, []
    print(printed.getvalue())  # noqa: T201
    return collector.items, [f"pytest collection failed (exit {int(code)})"]


def main() -> int:
    from immich_memories.cli import main as cli_main
    from immich_memories.memory_types.registry import OFFERED_MEMORY_TYPES

    inventory = load_inventory(INVENTORY.read_text(encoding="utf-8"))
    rows = inventory.rows
    required = (
        cli_surfaces(cli_main)
        | memory_type_surfaces(t.value for t in OFFERED_MEMORY_TYPES)
        | detector_surfaces(AUTOMATION)
    )
    errors = list(inventory.errors)
    errors += duplicate_ids(rows)
    errors += [f"advertised but in no row's covers: {s}" for s in uncovered(required, rows)]
    errors += doc_errors(rows, DOCS, ROOT / "README.md")
    ratchet_errors, note = gap_ratchet(rows, inventory.gap_ceiling)
    errors += ratchet_errors
    collected, collect_errors = collect_feature_tests(rows)
    collected |= collect_node_tests(rows)
    errors += collect_errors
    errors += link_errors(rows, collected)
    errors += unrun_test_errors(rows, MAKEFILE.read_text(encoding="utf-8"))

    tested = sum(bool(row.tests) and not row.status for row in rows)
    lane = sum(row.status.startswith("lane_only") for row in rows)
    gaps = sum(row.is_gap for row in rows)
    print(  # noqa: T201
        f"\nFeature inventory: {len(rows)} rows, {tested} tested, {lane} lane_only, {gaps} gap"
    )
    if note:
        print(note)  # noqa: T201
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)  # noqa: T201
    if errors:
        print(f"feature-check FAILED: {len(errors)} problem(s)", file=sys.stderr)  # noqa: T201
        return 1
    print("feature-check passed")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
