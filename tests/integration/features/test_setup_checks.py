"""The checks a new install runs before its first film: preflight, capabilities, a title preview."""

from __future__ import annotations

import json

import pytest

from tests.features.cli_harness import UserHome, film_facts


@pytest.mark.feature("preflight.basic-setup")
@pytest.mark.parametrize("flags", [(), ("--verbose",)], ids=["plain", "verbose"])
def test_preflight_on_a_basic_setup_passes_and_names_each_check(library_home: UserHome, flags):
    # The scripted route stands in for `models fetch`, which a Basic install has run.
    result = library_home.run("preflight", *flags, scripted_selection=True)

    assert result.returncode == 0, result.explain()
    for check in ("Immich", "Encoder", "Output directory", "Store location"):
        assert check in result.stdout, result.explain()
    assert "Preflight complete" in result.stdout
    assert (
        "0 errors" in result.stdout or " error" not in result.stdout.split("Preflight complete")[-1]
    )


@pytest.mark.feature("capabilities.json")
def test_capabilities_json_lists_each_capability_with_a_status(library_home: UserHome):
    result = library_home.run("capabilities", "--json")

    assert result.returncode == 0, result.explain()
    rows = json.loads(result.stdout)["capabilities"]
    assert rows
    assert all({"name", "status", "message"} <= set(row) for row in rows)
    assert any(row["name"].startswith("Selection tier: basic") for row in rows)


@pytest.mark.feature("titles.test-preview")
@pytest.mark.parametrize(
    ("orientation", "size"), [("landscape", (1280, 720)), ("portrait", (720, 1280))]
)
def test_titles_test_renders_a_title_preview_film(
    library_home: UserHome, tmp_path, orientation, size
):
    output = tmp_path / f"title-{orientation}.mp4"

    result = library_home.run(
        "titles",
        "test",
        "--year",
        "2024",
        "--orientation",
        orientation,
        "--resolution",
        "720p",
        "--output",
        str(output),
    )

    assert result.returncode == 0, result.explain()
    facts = film_facts(output)
    assert (facts.width, facts.height) == size
    assert 1.0 < facts.duration < 10.0
