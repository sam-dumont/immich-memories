# CLI demo recording. The only consumer is the Remotion demo's CliScene
# (docs-site/remotion/src/scenes/CliScene.tsx), which plays it sped up.
#
# Nothing is simulated: scripts/demo-cli-hermetic.py runs the real CLI against
# the hermetic fake Immich and the scripted editorial route from tests/e2e,
# over the CC0 fixture library: generate, then runs story, then runs why, in and out.
# It also writes docs-site/remotion/src/cli-timing.ts, the second each command
# starts at, which is where CliScene cuts the recording.
#
# Requires: vhs (brew install vhs). As root in a container, VHS_NO_SANDBOX=true.

Output "docs-site/remotion/public/cli-demo.mp4"

Set FontSize 18
Set Width 1400
Set Height 780
Set Theme "GitHub Dark"
Set Padding 24
Set TypingSpeed 20ms
# VHS stamps each captured frame at 1/Framerate. A machine that cannot keep up
# drops frames and the recording runs short of the wall clock, which moves the
# cuts cli-timing.ts records. 10 fps keeps up; run nothing heavy beside it, and
# `make demo-cli` checks the recording's length against the last mark.
Set Framerate 10

# The wrapper spends half a minute importing and starting the fakes before the
# first command. None of that is the product: start it hidden, and show the
# terminal from the moment it clears the screen and prints its prompt.
Hide
Type "DEMO_CLI_TIMING=docs-site/remotion/src/cli-timing.ts uv run python scripts/demo-cli-hermetic.py"
Enter
Wait+Screen@300s /❯/
Show
# The run's length depends on the machine, so wait for the shell prompt to come
# back (VHS's default Wait pattern) rather than guess a Sleep.
Wait@600s
Sleep 1s
