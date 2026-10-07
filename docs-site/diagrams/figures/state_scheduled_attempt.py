"""A scheduled attempt's states. Message: every attempt ends one of four ways, and the lock always comes back."""

from diagrams import Edge
from kit import code, diagram, finish, group, hue_edge, icon, main_edge, node, same_rank

STEM = "state-scheduled-attempt"

with diagram(STEM, nodesep="0.4", ranksep="0.7"):
    start = node(
        "A trigger", icon("mdi:timer-outline", "machine"), px=44, sub="timer, HTTP, or a suggestion"
    )
    lock = node("<b>Take the lock</b>", icon("mdi:lock-outline", "machine"), px=48, group="spine")
    held = node(
        "held elsewhere",
        icon("mdi:skip-next-circle-outline", "neutral"),
        px=36,
        sub="409, no attempt row",
    )
    running = node(
        "<b>running</b>",
        icon("mdi:progress-clock", "machine"),
        px=48,
        group="spine",
        sub="attempt row written",
    )
    ends = group(
        [
            (
                "<b>skipped</b>",
                icon("mdi:skip-next-circle-outline", "neutral"),
                "cooldown, nothing due, or nothing<br/>worth a film (sits out 7 d)",
            ),
            ("<b>dry_run</b>", icon("mdi:eye-outline", "neutral"), code("auto run --dry-run")),
            (
                "<b>completed</b>",
                icon("mdi:check-circle-outline", "keep"),
                "the film, or a pending<br/>upload went through",
            ),
            (
                "<b>failed</b>",
                icon("mdi:close-circle-outline", "drop"),
                "timeout, exit code, no film;<br/>from the 2nd in a row,<br/>backoff 24 h, 3 d, 7 d",
            ),
        ],
        cols=1,
        px=36,
    )
    release = node(
        "lock released", icon("mdi:lock-open-outline", "keep"), px=36, sub="in every case"
    )

    start >> Edge(**main_edge()) >> lock
    lock >> Edge(**main_edge(weight="20")) >> running
    same_rank(lock, held)
    lock >> Edge(**hue_edge("neutral")) >> held
    running >> Edge(**main_edge(weight="20")) >> ends
    ends >> Edge(**main_edge(penwidth="1.6")) >> release

finish(STEM)
