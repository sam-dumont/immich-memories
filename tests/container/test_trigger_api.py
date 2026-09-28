"""The trigger API, called exactly the way the shipped Kubernetes CronJob calls it."""

from __future__ import annotations

import json

import pytest

from tests.container.deployment import TRIGGER_TOKEN

pytestmark = [pytest.mark.container]

_READ_ATTEMPT = """
import json, sys
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.db import open_store
attempt = AutomationStateStore(open_store()).get_attempt(sys.argv[1])
print("ATTEMPT", json.dumps(None if attempt is None else
      {"outcome": attempt.outcome.value, "reason": attempt.reason}))
"""


def _recorded(deployment, attempt_id: str) -> dict | None:
    """The attempt as the store holds it, read by a process of its own."""
    output = deployment.compose(
        "exec", "-T", "immich-memories", "python", "-c", _READ_ATTEMPT, attempt_id
    )
    # Logging shares the stream, so the answer is the one line that says it is.
    answer = [line for line in output.splitlines() if line.startswith("ATTEMPT ")]
    assert answer, output[-4000:]
    return json.loads(answer[-1].removeprefix("ATTEMPT "))


def test_the_cronjob_request_is_accepted_and_its_attempt_recorded(deployment, upgraded):
    answer = json.loads(
        deployment.curl(
            "-fsS", "-X", "POST", deployment.trigger_url(), "-H", f"x-api-key: {TRIGGER_TOKEN}"
        )
    )

    assert answer["status"] == "accepted"
    attempt_id = answer["attempt_id"]
    assert _recorded(deployment, attempt_id) is not None

    # No Immich answers this deployment: the run fails, and the history says so.
    def finished() -> dict | None:
        attempt = _recorded(deployment, attempt_id)
        return attempt if attempt and attempt["outcome"] != "running" else None

    outcome = deployment.wait_for(finished, "the triggered attempt to finish")
    polled = json.loads(
        deployment.curl(
            "-fsS",
            deployment.trigger_url(f"/{attempt_id}"),
            "-H",
            f"x-api-key: {TRIGGER_TOKEN}",
        )
    )
    assert polled["attempt_id"] == attempt_id
    assert polled["state"] == outcome["outcome"]


def test_a_wrong_token_is_refused_with_401(deployment, upgraded):
    code = deployment.curl(
        "-sS",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "-X",
        "POST",
        deployment.trigger_url(),
        "-H",
        "x-api-key: not-the-token",
    )

    assert code.strip() == "401"
