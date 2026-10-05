"""A Mac. Message: one Python install, and a launchd agent that runs it once a day."""

from diagrams import Cluster, Edge
from kit import (
    cluster,
    code,
    diagram,
    finish,
    group,
    icon,
    main_edge,
    node,
    opt_edge,
    same_rank,
    titled,
)

STEM = "deploy-mac"

with diagram(STEM, nodesep="0.55", ranksep="0.9"):
    with Cluster("Your Mac", graph_attr=cluster("machine")):
        launchd = node(
            "launchd agent",
            icon("si:apple", "machine"),
            px=48,
            sub=code("auto install") + ", daily",
        )
        app = node(
            "<b>immich-memories</b>",
            icon("si:python", "machine"),
            px=72,
            group="spine",
            sub=code(".venv") + " from uv",
        )
        local = group(
            [
                ("FFmpeg", icon("si:ffmpeg", "machine"), "on PATH"),
                ("Config + store", icon("mdi:database", "machine"), code("~/.immich-memories")),
                ("Films", icon("mdi:folder-play-outline", "machine"), code("~/Videos/Memories")),
            ],
            cols=3,
            px=40,
        )
        with Cluster("helpers", graph_attr=titled("optional", "Optional, on the Mac", dashed=True)):
            helpers = group(
                [
                    (
                        "llama-server reader",
                        icon("mdi:robot-outline", "machine"),
                        "blank " + code("base_url"),
                    ),
                    ("ACE-Step", icon("mdi:music-note", "machine"), code("make install-acestep")),
                ],
                cols=2,
                px=40,
            )
    with Cluster("Your network", graph_attr=cluster("network")):
        immich = node(
            "<b>Immich</b>", icon("mdi:image-album", "network"), px=72, group="spine", sub="API key"
        )
        aceapi = node("ACE-Step API", icon("mdi:music-note", "network"), px=40, sub="optional")

    launchd >> Edge(**main_edge()) >> app
    app >> Edge(**main_edge(weight="20")) >> immich
    same_rank(app, local, helpers)
    helpers >> Edge(style="invis") >> local >> Edge(style="invis") >> app
    app >> Edge(**opt_edge(lhead="cluster_helpers")) >> helpers
    app >> Edge(**opt_edge()) >> aceapi

finish(STEM)
