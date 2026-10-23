"""Release notes group every commit under the heading a reader looks for, with its PR."""

from __future__ import annotations

import subprocess

from scripts.release_notes import changes, main

PREVIOUS, CURRENT = "v1.0.0-rc.10", "v1.0.0"


def _section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(f"### {heading}") + 1
    end = next((i for i in range(start, len(lines)) if not lines[i].startswith("* ")), len(lines))
    return lines[start:end]


def test_each_commit_lands_under_its_heading_with_its_pull_request():
    notes = changes(
        [
            "feat(people): suggest the relationships the family tree implies (#2801)",
            "perf(render): keep frames on the GPU from decode to encode (#2759)",
            "fix(render): a clip that decodes to no frame leaves the film (#2826)",
            "fix(security): sign-in on by default (#2567)",
            "fix(deps): apprise 1.13.1 for a CVE (#2559)",
            "build(deps): bump uv from 0.13.1 to 0.13.4 in /docker (#2778)",
            "fix(ci): retry a registry's 502 (#2700)",
            "docs: catch up with the last fixes (#2805)",
            "refactor(analysis): packages by stage (#2581)",
        ],
        PREVIOUS,
        CURRENT,
    )

    assert _section(notes, "🚀 Features") == [
        "* suggest the relationships the family tree implies"
        " in https://github.com/sam-dumont/immich-memories/pull/2801"
    ]
    assert len(_section(notes, "🔒 Security")) == 2
    assert _section(notes, "⚡ Performance")[0].startswith("* keep frames on the GPU")
    assert _section(notes, "🐛 Bug fixes")[0].startswith("* a clip that decodes")
    assert _section(notes, "📦 Dependencies")[0].startswith("* bump uv")
    assert _section(notes, "🔧 Build, CI and tests")[0].startswith("* retry a registry")
    assert _section(notes, "📚 Documentation")[0].startswith("* catch up")
    assert _section(notes, "🧹 Cleanup")[0].startswith("* packages by stage")
    assert notes.rstrip().endswith(
        "https://github.com/sam-dumont/immich-memories/compare/v1.0.0-rc.10...v1.0.0"
    )


def test_a_breaking_change_says_so_and_an_empty_group_has_no_heading():
    notes = changes(
        ["feat(api)!: the trigger answers 202 (#10)", "Merge branch 'x'"], PREVIOUS, CURRENT
    )

    assert "* **Breaking:** the trigger answers 202" in notes
    assert "### 🐛 Bug fixes" not in notes


def test_the_highlights_come_first_then_the_commits_since_the_previous_tag(
    tmp_path, capsys, monkeypatch
):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    def commit(message):
        git(
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
        )

    git("init", "-q")
    commit("fix: before (#1)")
    git("tag", PREVIOUS)
    commit("fix(render): after (#2)")
    highlights = tmp_path / "highlights.md"
    highlights.write_text("# v1.0.0\n\n## Highlights\n")

    monkeypatch.chdir(tmp_path)
    main([PREVIOUS, CURRENT, "--highlights", str(highlights)])
    out = capsys.readouterr().out

    assert out.startswith("# v1.0.0\n\n## Highlights\n\n## What's Changed")
    assert "* after in https://github.com/sam-dumont/immich-memories/pull/2" in out
    assert "before" not in out
