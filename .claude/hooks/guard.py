#!/usr/bin/env python3
"""PreToolUse guard for Bash: refuse the commands that have hurt this repo before.

Exit code 2 blocks the call and hands the message back to Claude.
"""

import json
import re
import shlex
import sys

RULES = (
    (
        re.compile(
            r"\bgit\b[^|;&]*\bcommit\b[^|;&]*--no-verify|\bgit\b[^|;&]*\bcommit\b[^|;&]*\s-n\b"
        ),
        "Commits go through the pre-commit hook; fix what it reports instead of skipping it.",
    ),
    (
        re.compile(r"(^|[\s;&|(])SKIP=\S+[^|;&]*\bgit\b[^|;&]*\bcommit\b"),
        "Commits go through every pre-commit hook; SKIP= is not used here.",
    ),
    (
        re.compile(r"\bgit\b[^|;&]*\badd\b[^|;&]*(\s-f\b|--force\b)"),
        "Ignored files stay out of the repo; change .gitignore in a PR if something should be tracked.",
    ),
    (
        re.compile(r"until\s+!\s*pgrep\s+-f"),
        "A pgrep -f loop matches its own command line and never ends; poll a log file or gh instead.",
    ),
)


UNSEALED = (
    "That pytest run keeps the real HOME and store (a test overwrote the maintainer's config this "
    "way). Use the default addopts, or the integration suite's make target."
)
REAL_WORLD = re.compile(r"^\s*(integration|container|e2e)\b")


def _unsealed_pytest(command: str) -> bool:
    """An -m that is empty or selects integration/container/e2e, or a cleared addopts."""
    if not re.search(r"\bpytest\b", command):
        return False
    if re.search(r"-o\s*addopts=", command):
        return True
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    for index, word in enumerate(words):
        if word == "-m" and index + 1 < len(words):
            value = words[index + 1]
        elif word.startswith("-m="):
            value = word[3:]
        else:
            continue
        if not value.strip() or REAL_WORLD.match(value):
            return True
    return False


def main() -> int:
    event = json.load(sys.stdin)
    command = (event.get("tool_input") or {}).get("command") or ""
    if _unsealed_pytest(command):
        print(f"Blocked by .claude/hooks/guard.py: {UNSEALED}", file=sys.stderr)
        return 2
    for pattern, reason in RULES:
        if pattern.search(command):
            print(f"Blocked by .claude/hooks/guard.py: {reason}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
