"""A scheduled run. Message: once a day it checks what's due and makes at most one film."""

from diagrams import Edge
from kit import code, diagram, finish, icon, ladder, node, opt_edge, same_rank

STEM = "seq-scheduled-run"
SKIP = icon("mdi:skip-next-circle-outline", "neutral")

with diagram(STEM, nodesep="0.3", ranksep="0.4"):
    film = ladder(
        (
            "A timer fires",
            icon("mdi:timer-outline", "machine"),
            "in-process, " + code("auto run") + ",<br/>or " + code("POST /api/trigger"),
        ),
        [
            {
                "q": "Another run<br/>holds the lock?",
                "icon": icon("mdi:lock-outline", "neutral"),
                "exit": ("stops", SKIP, "HTTP: 409; no attempt written", "neutral"),
            },
            {
                "q": "Cooldown<br/>still active?",
                "icon": icon("mdi:timer-sand", "neutral"),
                "sub": "24 h by default;<br/>pending uploads retried first",
                "exit": ("skipped", SKIP, "cooldown active", "neutral"),
            },
            {
                "q": "Nothing due?",
                "icon": icon("mdi:calendar-search", "neutral"),
                "sub": "month, trip, season, holiday, album,<br/>person month, or a month never made",
                "exit": (
                    "skipped",
                    SKIP,
                    "no eligible candidates,<br/>rare: old months fill quiet nights",
                    "neutral",
                ),
            },
            {
                "q": "The film run<br/>fails?",
                "icon": icon("mdi:movie-open-play", "machine"),
                "sub": code("generate --source=auto") + "<br/>2 h limit",
                "exit": (
                    "failed",
                    icon("mdi:close-circle-outline", "drop"),
                    "from the second failure:<br/>24 h, 3 days, 7 days",
                    "drop",
                ),
            },
        ],
        (
            "Completed",
            icon("mdi:movie-check-outline", "keep"),
            "one film, uploaded<br/>if you asked",
        ),
    )
    notify = node(
        "Notification",
        icon("mdi:bell-ring-outline", "outside"),
        px=36,
        sub="success or failure,<br/>if notifications are on",
    )
    same_rank(film, notify)
    film >> Edge(**opt_edge()) >> notify

finish(STEM)
