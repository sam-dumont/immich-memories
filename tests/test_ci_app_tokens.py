"""GITHUB_TOKEN only reads where the CI GitHub App can write instead.

The app (immich-memories-ci-bot) mints a one-hour token per step that writes, scoped to one
repository and the permissions that step needs. The release job's token is pinned in
`test_release_ref_push.py`; these are the other workflows it reaches.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / ".github/workflows/mirror.yml"
DOCS = ROOT / ".github/workflows/docs.yml"


def test_the_mirror_posts_its_pending_status_with_a_status_only_app_token():
    workflow = yaml.safe_load(MIRROR.read_text())
    assert workflow["permissions"] == {"contents": "read"}
    steps = workflow["jobs"]["mirror"]["steps"]
    names = [step.get("name") for step in steps]
    mint = steps[names.index("Mint a status token")]
    assert mint["id"] == "status-token"
    assert mint["uses"].startswith("actions/create-github-app-token@")
    assert mint["with"]["repositories"] == "immich-memories"
    permissions = {
        key: value for key, value in mint["with"].items() if key.startswith("permission-")
    }
    assert permissions == {"permission-statuses": "write"}
    assert names.index("Mint a status token") < names.index("Set pending status")
    pending = steps[names.index("Set pending status")]
    # The minted token's output, never a stored secret or GITHUB_TOKEN.
    assert pending["env"]["GH_TOKEN"].split() == ["${{", "steps.status-token.outputs.token", "}}"]
    assert "github.token" not in yaml.safe_dump(steps)


def _needs(job):
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else needs


def test_a_release_the_ci_app_publishes_does_not_start_a_second_docs_deploy():
    """release.yml calls the docs deploy itself; the `release` event its app token fires must not.

    A release GITHUB_TOKEN published never fired that event. The app token's does, and its run
    in the deploy's concurrency group would cancel the deploy release.yml called.
    """
    workflow = yaml.safe_load(DOCS.read_text())
    bot = "github.event.sender.login == 'immich-memories-ci-bot[bot]'"
    group = workflow["concurrency"]["group"]
    assert bot in group
    assert "'docs-deploy'" in group
    assert bot in workflow["jobs"]["plan"]["if"]
    # Every other job waits on plan, so skipping plan skips the deploy.
    jobs = workflow["jobs"]
    for name in jobs:
        reached, todo = set(), [name]
        while todo:
            for parent in _needs(jobs[todo.pop()]):
                if parent not in reached:
                    reached.add(parent)
                    todo.append(parent)
        assert name == "plan" or "plan" in reached, name
