"""`make feature-check`: every advertised feature has a feature test or a stated reason."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_feature_inventory import (  # noqa: E402
    Row,
    cli_surfaces,
    detector_surfaces,
    doc_errors,
    duplicate_ids,
    gap_ratchet,
    heading_anchors,
    link_errors,
    load_inventory,
    memory_type_surfaces,
    uncovered,
)


def _commands() -> click.Group:
    @click.group()
    @click.option("--config")
    def root(config):
        raise AssertionError("the check never invokes a callback")

    @root.group()
    def runs():
        raise AssertionError("the check never invokes a callback")

    @runs.command()
    @click.option("--keep-output", is_flag=True)
    @click.option("--secret-debug", hidden=True)
    def delete(keep_output, secret_debug):
        raise AssertionError("the check never invokes a callback")

    @root.command(hidden=True)
    def internal():
        raise AssertionError("the check never invokes a callback")

    return root


def _inventory(body: str) -> str:
    return "gap_ceiling: 1\nfeatures:\n" + textwrap.indent(textwrap.dedent(body), "  ")


def test_every_visible_command_and_flag_is_a_surface_to_cover():
    assert cli_surfaces(_commands()) == {
        "cli:--config",
        "cli:runs",
        "cli:runs delete",
        "cli:runs delete --keep-output",
    }


def test_memory_types_and_detectors_are_surfaces_too(tmp_path):
    (tmp_path / "calendar.py").write_text(
        "class MonthlyDetector:\n    pass\n\nclass Helper:\n    pass\n"
    )
    (tmp_path / "trips.py").write_text("class TripDetector:\n    pass\n")

    assert memory_type_surfaces(["trip"]) == {"memory-type:trip"}
    assert detector_surfaces(tmp_path) == {"detector:MonthlyDetector", "detector:TripDetector"}


def test_a_surface_no_row_covers_is_reported():
    rows = [Row(id="runs.delete", promise="p", doc="d", covers=("cli:runs delete",))]

    assert uncovered({"cli:runs delete", "cli:runs delete --keep-output"}, rows) == [
        "cli:runs delete --keep-output"
    ]


def test_a_row_needs_tests_or_a_lane_only_or_gap_status():
    inventory = load_inventory(
        _inventory(
            """
            - id: a.tested
              promise: p
              doc: d.md
              tests: [tests/x.py::test_a]
            - id: b.lane
              promise: p
              doc: d.md
              status: "lane_only: needs NVENC"
            - id: c.gap
              promise: p
              doc: d.md
              status: "gap: #2346"
            - id: d.nothing
              promise: p
              doc: d.md
            - id: e.vague
              promise: p
              doc: d.md
              status: "todo"
            - id: f.lane-with-tests
              promise: p
              doc: d.md
              tests: [tests/x.py::test_f]
              status: "lane_only: real NAS"
            """
        )
    )

    assert inventory.errors == [
        "d.nothing: needs feature tests or a lane_only/gap status",
        "e.vague: status must be 'lane_only: <reason>' or 'gap: #<issue>'",
        "e.vague: needs feature tests or a lane_only/gap status",
        "f.lane-with-tests: a row with tests may only carry a gap status",
    ]


def test_a_row_must_be_well_formed():
    inventory = load_inventory(
        _inventory(
            """
            - id: Bad Id
              promise: ""
              doc: d.md
              status: "gap: #1"
              colour: blue
            """
        )
    )

    assert inventory.errors == [
        "Bad Id: unknown keys ['colour']",
        "Bad Id: id must match ^[a-z0-9]+(?:[.\\-_][a-z0-9]+)*$",
        "Bad Id: promise is required",
    ]


def test_duplicate_ids_are_reported():
    rows = [Row(id="x", promise="p", doc="d"), Row(id="x", promise="q", doc="d")]

    assert duplicate_ids(rows) == ["x: duplicate id"]


def test_the_gap_count_is_a_ratchet():
    gaps = [Row(id=f"g{i}", promise="p", doc="d", status="gap: #1") for i in range(3)]
    lane = [Row(id="l", promise="p", doc="d", status="lane_only: GPU")]

    over, _ = gap_ratchet(gaps + lane, ceiling=2)
    equal = gap_ratchet(gaps + lane, ceiling=3)
    under = gap_ratchet(gaps[:1] + lane, ceiling=3)

    assert over and "3 gap rows, ceiling 2" in over[0]
    assert equal == ([], "")
    assert under == ([], "gap rows 1 < ceiling 3: lower gap_ceiling to 1")


def test_listed_tests_must_collect_and_carry_their_rows_marker():
    rows = [
        Row(id="a", promise="p", doc="d", tests=("t.py::test_a", "t.py::test_gone")),
        Row(id="b", promise="p", doc="d", tests=("t.py::test_b",)),
    ]
    collected = {
        "t.py::test_a": ["a"],
        "t.py::test_b": [],
        "t.py::test_stray": ["a"],
        "t.py::test_orphan": ["nowhere"],
    }

    assert link_errors(rows, collected) == [
        "a: test t.py::test_gone does not collect",
        "b: test t.py::test_b lacks @pytest.mark.feature('b')",
        "t.py::test_orphan: marked feature('nowhere'), which no row has",
        "a: marked test t.py::test_stray is not listed in its row",
    ]


def test_headings_become_docusaurus_anchors():
    page = textwrap.dedent(
        """
        # Generate a film
        ## Review before rendering
        ## Docker: switch on the built-in timer
        ## `runs render`
        ## OIDC / SSO
        ### Custom {#my-anchor}
        ```bash
        # not a heading
        ```
        """
    )

    assert heading_anchors(page) == {
        "generate-a-film",
        "review-before-rendering",
        "docker-switch-on-the-built-in-timer",
        "runs-render",
        "oidc--sso",
        "my-anchor",
    }


def test_a_doc_page_or_anchor_that_does_not_exist_is_reported(tmp_path):
    docs = tmp_path / "docs"
    (docs / "make").mkdir(parents=True)
    (docs / "make" / "generate.md").write_text("# Generate\n## Output\n")
    readme = tmp_path / "README.md"
    readme.write_text("# Immich Memories\n")
    rows = [
        Row(id="ok", promise="p", doc="make/generate.md#output"),
        Row(id="readme", promise="p", doc="README.md#immich-memories"),
        Row(id="no-anchor", promise="p", doc="make/generate.md#examples"),
        Row(id="no-page", promise="p", doc="make/missing.md"),
    ]

    assert doc_errors(rows, docs, readme) == [
        "no-anchor: make/generate.md has no heading #examples",
        "no-page: doc page 'make/missing.md' does not exist",
    ]


def test_the_committed_inventory_parses_cleanly():
    root = Path(__file__).resolve().parent.parent
    inventory = load_inventory((root / "tests" / "features" / "inventory.yaml").read_text())

    assert inventory.errors == []
    assert duplicate_ids(inventory.rows) == []
    assert gap_ratchet(inventory.rows, inventory.gap_ceiling)[0] == []
