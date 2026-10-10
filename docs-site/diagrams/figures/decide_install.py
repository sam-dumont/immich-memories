"""Install lane. Message: pick the lane you already run; every lane gets the same app."""

from kit import code, diagram, finish, icon, ladder

STEM = "decide-install"

with diagram(STEM, nodesep="0.3", ranksep="0.4"):
    ladder(
        ("What do you<br/>already run?", icon("mdi:help-circle-outline", "machine"), ""),
        [
            {
                "q": "A Kubernetes<br/>cluster?",
                "icon": icon("si:kubernetes", "neutral"),
                "exit": [
                    (
                        "Terraform module",
                        icon("si:terraform", "keep"),
                        "if Terraform<br/>manages it",
                        "keep",
                    ),
                    (
                        "Kustomize",
                        icon("mdi:file-tree-outline", "keep"),
                        code("deploy/kubernetes"),
                        "keep",
                    ),
                ],
            },
            {
                "q": "A NAS with a<br/>container manager?",
                "icon": icon("mdi:nas", "neutral"),
                "exit": (
                    "Single-file stack",
                    icon("mdi:nas", "keep"),
                    "exported by the setup builder",
                    "keep",
                ),
            },
            {
                "q": "Docker on<br/>the machine?",
                "icon": icon("si:docker", "neutral"),
                "exit": (
                    "docker-compose.yml",
                    icon("si:docker", "keep"),
                    "choose Basic, GPU or Full",
                    "keep",
                ),
            },
        ],
        ("uv or pip", icon("si:python", "keep"), "FFmpeg on PATH"),
    )

finish(STEM)
