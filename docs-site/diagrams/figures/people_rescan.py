"""What a rescan keeps. Message: a rescan redraws the guesses, and your answers stay."""

from kit import diagram, finish, icon, ladder

STEM = "people-rescan"
KEPT = icon("mdi:check-circle-outline", "keep")

with diagram(STEM, nodesep="0.45", ranksep="0.35"):
    ladder(
        ("A rescan", icon("mdi:text-search", "machine"), "reads Immich again"),
        [
            {
                "q": "Typed by<br/>you?",
                "icon": icon("mdi:form-select", "neutral"),
                "sub": "role, notes, birth date",
                "exit": ("kept", KEPT, "never overwritten", "keep"),
            },
            {
                "q": "An owner<br/>you picked?",
                "icon": icon("mdi:key-variant", "neutral"),
                "sub": "per account",
                "exit": ("kept", KEPT, "a scan only guesses", "keep"),
            },
            {
                "q": "Someone<br/>you added?",
                "icon": icon("mdi:account-group", "neutral"),
                "sub": "not in Immich",
                "exit": ("kept", KEPT, "stays in the registry", "keep"),
            },
            {
                "q": "In a saved<br/>group?",
                "icon": icon("mdi:format-list-checks", "neutral"),
                "exit": (
                    "kept",
                    KEPT,
                    "the group and its people,<br/>even under the floor",
                    "keep",
                ),
            },
            {
                "q": "A link you<br/>named?",
                "icon": icon("mdi:check-circle-outline", "neutral"),
                "exit": ("kept", KEPT, "one row per pair,<br/>both sides", "keep"),
            },
            {
                "q": "A link you<br/>rejected?",
                "icon": icon("mdi:cancel", "neutral"),
                "exit": ("kept", KEPT, "stays rejected,<br/>no new flag", "keep"),
            },
        ],
        (
            "Redrawn",
            icon("mdi:swap-horizontal", "machine"),
            "tiers, counts and<br/>new guesses",
        ),
    )

finish(STEM)
