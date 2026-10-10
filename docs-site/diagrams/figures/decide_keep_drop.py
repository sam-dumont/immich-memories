"""Keep or drop: a favourite helps, but source and sharing checks still apply."""

from kit import diagram, finish, icon, ladder

STEM = "decide-keep-drop"
DROP = icon("mdi:close-circle-outline", "drop")
STAR = icon("mdi:star", "star")

with diagram(STEM, nodesep="0.3", ranksep="0.35"):
    ladder(
        ("Every picture<br/>in the period", icon("mdi:image-multiple-outline", "machine"), ""),
        [
            {
                "q": "Hidden or<br/>trashed?",
                "icon": icon("mdi:eye-off-outline", "neutral"),
                "exit": ("dropped", DROP, "a star doesn't help", "drop"),
            },
            {
                "q": "Screenshot or<br/>document?",
                "icon": icon("mdi:file-document-outline", "neutral"),
                "exit": (
                    "dropped",
                    DROP,
                    "a pin exempts only the<br/>personal-document check",
                    "drop",
                ),
            },
            {
                "q": "Shot<br/>elsewhere?",
                "icon": icon("mdi:map-marker-radius-outline", "neutral"),
                "exit": ("a favourite<br/>gets through", STAR, "others are dropped", "star"),
            },
            {
                "q": "Not the film's<br/>people?",
                "icon": icon("mdi:account-group", "neutral"),
                "exit": ("dropped", DROP, "a star doesn't help", "drop"),
            },
            {
                "q": "Family-viewing<br/>hold?",
                "icon": icon("mdi:eye-check-outline", "neutral"),
                "exit": ("dropped", DROP, "until you clear it", "drop"),
            },
            {
                "q": "Repeats a<br/>kept shot?",
                "icon": icon("mdi:content-copy", "neutral"),
                "exit": (
                    "favourites win<br/>over unstarred shots",
                    STAR,
                    "two starred repeats<br/>can still become one",
                    "star",
                ),
            },
        ],
        (
            "In the pool",
            icon("mdi:movie-filter-outline", "keep"),
            "stories pick from it,<br/>favourites first",
        ),
    )

finish(STEM)
