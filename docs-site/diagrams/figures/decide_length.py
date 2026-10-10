"""Length. Message: a film is as long as its distinct shots can carry, and never padded."""

from kit import code, diagram, finish, icon, ladder

STEM = "decide-length"

with diagram(STEM, nodesep="0.3", ranksep="0.4"):
    ladder(
        ("How long?", icon("mdi:timer-sand", "machine"), ""),
        [
            {
                "q": code("--duration") + "?",
                "icon": icon("mdi:ruler", "neutral"),
                "exit": ("that target", icon("mdi:check-circle-outline", "machine"), "", "machine"),
            },
            {
                "q": code("--short-form") + "?",
                "icon": icon("mdi:cellphone", "neutral"),
                "exit": (
                    "15, 30, 60 or 90 s",
                    icon("mdi:cellphone", "machine"),
                    "portrait, unless you<br/>pick another shape",
                    "machine",
                ),
            },
            {
                "q": "Too few<br/>distinct shots?",
                "icon": icon("mdi:content-copy", "neutral"),
                "sub": "month: 60 s; trip: 60–300 s<br/>from photographed days",
                "exit": (
                    "shorter",
                    icon("mdi:arrow-collapse-horizontal", "star"),
                    "what the distinct shots<br/>can hold, then on",
                    "star",
                ),
            },
            {
                "q": "Nothing worth<br/>a film?",
                "icon": icon("mdi:filter-outline", "neutral"),
                "exit": (
                    "no film",
                    icon("mdi:close-circle-outline", "drop"),
                    "Nothing worth a film",
                    "drop",
                ),
            },
        ],
        (
            "The film",
            icon("mdi:movie-check-outline", "keep"),
            "auto target rounded down to 5 s;<br/>ordinary titles: up to 20%",
        ),
    )

finish(STEM)
