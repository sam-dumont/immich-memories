"""--ask. Message: ask in a sentence; unprepared pictures get prepared first, then you get the film."""

from kit import diagram, finish, icon, ladder

STEM = "seq-ask"

with diagram(STEM, nodesep="0.3", ranksep="0.4"):
    ladder(
        (
            "generate --ask",
            icon("mdi:message-text-outline", "machine"),
            "“the kids at the beach<br/>last summer”",
        ),
        [
            {
                "q": "Not the<br/>Full tier?",
                "icon": icon("mdi:robot-outline", "neutral"),
                "exit": ("stops", icon("mdi:close-circle-outline", "drop"), "usage error", "drop"),
            },
            {
                "q": "Read the<br/>request",
                "icon": icon("mdi:text-search", "network"),
                "sub": "who, when, what:<br/>the reader answers 3 times,<br/>2 must agree",
            },
            {
                "q": "Pictures not<br/>prepared yet?",
                "icon": icon("mdi:image-search-outline", "neutral"),
                "exit": (
                    "prepares them",
                    icon("mdi:progress-clock", "star"),
                    "warns: N pictures, about T;<br/>shows progress, then on",
                    "star",
                ),
            },
            {
                "q": "The pool<br/>is empty?",
                "icon": icon("mdi:filter-outline", "neutral"),
                "exit": (
                    "not possible",
                    icon("mdi:close-circle-outline", "drop"),
                    "names the filter<br/>that emptied it",
                    "drop",
                ),
            },
        ],
        (
            "The film",
            icon("mdi:movie-check-outline", "keep"),
            "made like an album film;<br/>titled in your film language",
        ),
    )

finish(STEM)
