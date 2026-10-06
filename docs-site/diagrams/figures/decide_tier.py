"""Tier. Message: auto picks the most your hardware can do; set tier to choose yourself."""

from kit import code, diagram, finish, icon, ladder

STEM = "decide-tier"

with diagram(STEM, nodesep="0.3", ranksep="0.45"):
    ladder(
        ("tier", icon("mdi:tune-variant", "machine"), code("auto") + " unless you set it"),
        [
            {
                "q": "Set to basic,<br/>gpu or full?",
                "icon": icon("mdi:pin-outline", "neutral"),
                "sub": "Compose and Kubernetes<br/>start at basic",
                "exit": (
                    "that tier",
                    icon("mdi:check-circle-outline", "machine"),
                    "full also needs a reader",
                    "machine",
                ),
            },
            {
                "q": "No GPU found?",
                "icon": icon("mdi:expansion-card", "neutral"),
                "sub": "CUDA, MLX, Metal",
                "exit": (
                    "<b>Basic</b>",
                    icon("mdi:cpu-64-bit", "keep"),
                    "CPU, rules, no captions,<br/>up to 1080p",
                    "keep",
                ),
            },
            {
                "q": "No reader<br/>model on?",
                "icon": icon("mdi:robot-outline", "neutral"),
                "exit": (
                    "<b>GPU</b>",
                    icon("mdi:closed-caption-outline", "keep"),
                    "+ captions, document and<br/>sensitive checks,<br/>family-viewing pre-screen",
                    "keep",
                ),
            },
        ],
        ("Full", icon("mdi:robot-happy-outline", "keep"), "+ a model reads the period"),
    )

finish(STEM)
