"""A run that prints as log lines (no terminal) does so for that run only, not for the process.

`generate` without a terminal used to switch the CLI's printing to log lines and never switch it
back, so every later command in the same process, and every later test, printed nothing.
"""

from __future__ import annotations

from immich_memories.cli._helpers import print_info, quiet_output


def test_quiet_output_lasts_only_as_long_as_its_block(capsys):
    with quiet_output(True):
        print_info("while quiet")
    print_info("after the run")

    printed = capsys.readouterr().out
    assert "while quiet" not in printed
    assert "after the run" in printed
