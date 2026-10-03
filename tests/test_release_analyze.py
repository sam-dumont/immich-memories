"""A release run must resume an interrupted publication, not advance past it.

The release workflow pushes the version tag before GitHub Release creation; a
failure in between leaves a tag with no release. #1010: the next run must
publish that exact version again. "Tag exists" is not evidence that a release
completed.
"""

from scripts.release_analyze import (
    Decision,
    decide,
    format_outputs,
    published_baseline,
    sort_version_tags,
)


def _released(*tags: str):
    released = set(tags)
    return lambda tag: tag in released


def test_a_stranded_tag_is_resumed_with_the_same_version():
    """Failure after the tag push, before the GitHub Release: retry that version."""
    decision = decide(
        tags=["v0.101.0", "v0.100.8"],
        release_exists=_released("v0.100.8"),
        merged_branches="fix/…: merge fix",
        commit_bodies="fix(security): something\n",
        force_version=None,
    )
    assert decision == Decision(
        should_release=True,
        next_version="0.101.0",
        release_type="patch",
        resumed=True,
        previous_tag="v0.100.8",
    )


def test_a_stranded_tag_is_resumed_even_with_no_commits_after_the_baseline():
    """No releasable commits since the baseline must not read as nothing to do."""
    decision = decide(
        tags=["v0.101.0", "v0.100.8"],
        release_exists=_released("v0.100.8"),
        merged_branches="",
        commit_bodies="",
    )
    assert decision.should_release is True
    assert decision.next_version == "0.101.0"
    assert decision.resumed is True


def test_a_completed_version_reruns_as_a_no_op():
    decision = decide(
        tags=["v0.101.0"],
        release_exists=_released("v0.101.0"),
        merged_branches="",
        commit_bodies="",
    )
    assert decision.should_release is False


def test_a_fresh_release_still_bumps_from_the_published_baseline():
    decision = decide(
        tags=["v0.100.8"],
        release_exists=_released("v0.100.8"),
        merged_branches="",
        commit_bodies="feat(titles): new renderer\nfix(ui): a bug\n",
    )
    assert decision == Decision(
        should_release=True, next_version="0.101.0", release_type="minor", previous_tag="v0.100.8"
    )


def test_the_first_release_counts_the_whole_history():
    decision = decide(
        tags=[],
        release_exists=_released(),
        merged_branches="",
        commit_bodies="feat: the beginning\n",
    )
    assert decision.should_release is True
    assert decision.next_version == "0.1.0"


def test_force_version_overrides_a_fresh_bump_but_not_a_resume():
    forced = decide(
        tags=["v1.2.3"],
        release_exists=_released("v1.2.3"),
        merged_branches="",
        commit_bodies="fix: a bug\n",
        force_version="major",
    )
    assert forced.next_version == "2.0.0"

    resumed = decide(
        tags=["v1.2.4", "v1.2.3"],
        release_exists=_released("v1.2.3"),
        merged_branches="",
        commit_bodies="",
        force_version="major",
    )
    assert resumed.next_version == "1.2.4", "a stranded version is already chosen"


def test_the_breaking_change_footer_still_forces_a_major():
    decision = decide(
        tags=["v1.2.3"],
        release_exists=_released("v1.2.3"),
        merged_branches="",
        commit_bodies="fix(ui): a bug\n\nBREAKING CHANGE: config keys renamed\n",
    )
    assert decision.next_version == "2.0.0"


def test_outputs_carry_no_version_when_standing_down():
    assert format_outputs(Decision(should_release=False)) == {"should_release": "false"}
    outputs = format_outputs(
        Decision(should_release=True, next_version="0.101.0", release_type="patch")
    )
    assert outputs == {
        "should_release": "true",
        "next_version": "0.101.0",
        "release_type": "patch",
        "prerelease": "false",
        "previous_tag": "",
    }


def test_the_published_baseline_skips_unreleased_tags():
    assert published_baseline(["v0.101.0", "v0.100.8"], _released("v0.100.8")) == "v0.100.8"
    assert published_baseline(["v0.101.0"], _released("v0.101.0")) == "v0.101.0"
    assert published_baseline([], _released()) is None


def test_a_release_candidate_opens_a_series_from_the_stable_baseline():
    """The first candidate of a major takes -rc.1 on the forced core version."""
    decision = decide(
        tags=["v0.103.0"],
        release_exists=_released("v0.103.0"),
        merged_branches="",
        commit_bodies="fix: a bug\n",
        force_version="major",
        channel="rc",
    )
    assert decision == Decision(
        should_release=True,
        next_version="1.0.0-rc.1",
        release_type="major",
        previous_tag="v0.103.0",
        prerelease=True,
    )


def test_the_next_candidate_increments_the_open_series():
    """Candidates count up on the same core version, whatever the commits would bump."""
    decision = decide(
        tags=["v1.0.0-rc.1", "v0.103.0"],
        release_exists=_released("v1.0.0-rc.1", "v0.103.0"),
        merged_branches="",
        commit_bodies="feat: something\nfix: a bug\n",
        commits_since_latest="build(docker): repair the image\n",
        channel="rc",
    )
    assert decision.next_version == "1.0.0-rc.2"
    assert decision.release_type == "major"
    assert decision.prerelease is True
    assert decision.previous_tag == "v1.0.0-rc.1"


def test_a_candidate_with_nothing_new_since_the_last_one_stands_down():
    decision = decide(
        tags=["v1.0.0-rc.1", "v0.103.0"],
        release_exists=_released("v1.0.0-rc.1", "v0.103.0"),
        merged_branches="",
        commit_bodies="fix: a bug\n",
        commits_since_latest="",
        channel="rc",
    )
    assert decision.should_release is False


def test_a_stable_release_promotes_the_last_candidate():
    """The final ships what the candidates tested; notes span the whole series."""
    decision = decide(
        tags=["v1.0.0-rc.2", "v1.0.0-rc.1", "v0.103.0"],
        release_exists=_released("v1.0.0-rc.2", "v1.0.0-rc.1", "v0.103.0"),
        merged_branches="",
        commit_bodies="feat: something\n",
        commits_since_latest="docs: tidy the install page\n",
    )
    assert decision == Decision(
        should_release=True,
        next_version="1.0.0",
        release_type="major",
        previous_tag="v0.103.0",
    )


def test_a_stable_release_refuses_code_no_candidate_carried():
    decision = decide(
        tags=["v1.0.0-rc.1", "v0.103.0"],
        release_exists=_released("v1.0.0-rc.1", "v0.103.0"),
        merged_branches="",
        commit_bodies="feat: something\n",
        commits_since_latest="fix(render): late change\n",
    )
    assert decision.should_release is False
    assert "1.0.0-rc.2" in decision.note


def test_a_stranded_candidate_is_resumed_as_a_prerelease():
    decision = decide(
        tags=["v1.0.0-rc.1", "v0.103.0"],
        release_exists=_released("v0.103.0"),
        merged_branches="",
        commit_bodies="",
        channel="rc",
    )
    assert decision.next_version == "1.0.0-rc.1"
    assert decision.resumed is True
    assert decision.prerelease is True


def test_candidates_sort_below_their_final_version():
    """git's own version sort puts v1.0.0-rc.1 above v1.0.0; the baseline must not."""
    tags = sort_version_tags(["v1.0.0-rc.1", "v1.0.0", "v1.0.0-rc.10", "v1.0.0-rc.2", "v0.9.0"])
    assert tags == ["v1.0.0", "v1.0.0-rc.10", "v1.0.0-rc.2", "v1.0.0-rc.1", "v0.9.0"]


def test_app_only_dispatch_names_a_commit_without_requesting_a_release(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [sys.executable, str(Path("scripts/release_analyze.py").resolve()), "--app-only"],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_SHA": "a" * 40},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["should_release=false", "next_version=0+g" + "a" * 40]


def test_pre_tag_rehearsal_uses_a_unique_non_rc_identity(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/release_analyze.py"
    result = subprocess.run(
        [sys.executable, str(script), "--channel", "dev"],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert dict(line.split("=", 1) for line in result.stdout.splitlines()) == {
        "should_release": "true",
        "next_version": "0.0.0-dev.12345",
        "release_type": "development",
        "prerelease": "true",
        "previous_tag": "",
    }


def test_rehearsal_refuses_reruns_and_incomplete_artifact_modes(monkeypatch, capsys):
    import sys

    import pytest
    from scripts.release_analyze import main

    for run_id, attempt, extra in [
        ("", "1", []),
        ("12345", "2", []),
        ("12345", "1", ["--app-only"]),
        ("12345", "1", ["--inference-only"]),
    ]:
        monkeypatch.setenv("GITHUB_RUN_ID", run_id)
        monkeypatch.setenv("GITHUB_RUN_ATTEMPT", attempt)
        monkeypatch.setattr(sys, "argv", ["release_analyze.py", "--channel", "dev", *extra])
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 2
        assert capsys.readouterr().out == ""
    assert sort_version_tags(["v0.0.0-dev.12345", "v1.0.0-rc.1", "v0.103.0"]) == [
        "v1.0.0-rc.1",
        "v0.103.0",
    ]
