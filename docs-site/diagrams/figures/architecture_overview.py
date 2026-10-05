"""What runs where. Message: it all stays home unless you switch something on."""

from diagrams import Cluster, Edge
from kit import cluster, diagram, finish, group, icon, main_edge, node, opt_edge, same_rank

STEM = "architecture-overview"
OPTIONAL = "Optional, on your own hardware"
OUTSIDE = "The internet: each one off until you turn it on"

with diagram(STEM, nodesep="0.45", ranksep="0.8", ordering="out"):
    with Cluster("Your network", graph_attr=cluster("network")):
        with Cluster("Your machine", graph_attr=cluster("machine")):
            starts = group(
                [
                    ("Web UI", icon("si:svelte", "machine")),
                    ("Daily timer", icon("mdi:timer-outline", "machine")),
                ],
                cols=1,
            )
            app = node(
                "<b>immich-memories</b>",
                icon("mdi:movie-open-play", "machine"),
                px=72,
                group="spine",
            )
            helpers = group(
                [
                    ("FFmpeg", icon("si:ffmpeg", "machine")),
                    ("Store", icon("mdi:database", "machine")),
                ],
                cols=2,
                px=40,
            )
        immich = node(
            "<b>Immich</b>",
            icon("mdi:image-album", "network"),
            px=72,
            group="spine",
            sub="reads your photos,<br/>uploads the film if you ask",
        )
        with Cluster(OPTIONAL, graph_attr=cluster("optional", dashed=True)):
            extras = group(
                [
                    ("GPU box", icon("mdi:expansion-card", "network")),
                    ("Reader model", icon("mdi:robot-outline", "network")),
                    ("ACE-Step music", icon("mdi:music-note", "network")),
                ]
            )
        gate = node("Your router", icon("mdi:wall-fire", "neutral"), px=48, sub="closed by default")

    with Cluster(OUTSIDE, graph_attr=cluster("outside", dashed=True)):
        internet = group(
            [
                ("Place names,\nmap tiles", icon("mdi:map-marker-radius-outline", "outside")),
                ("Hosted\nreader", icon("mdi:cloud-outline", "outside")),
                ("Notifications", icon("mdi:bell-ring-outline", "outside")),
                ("Model\ndownloads", icon("si:huggingface", "outside")),
            ],
            cols=2,
        )

    starts >> Edge(**main_edge()) >> app
    app >> Edge(**main_edge(weight="20")) >> immich
    same_rank(app, helpers)
    helpers >> Edge(style="invis") >> app
    app >> Edge(**opt_edge()) >> gate
    app >> Edge(**opt_edge(lhead=f"cluster_{OPTIONAL}")) >> extras
    gate >> Edge(**opt_edge(lhead=f"cluster_{OUTSIDE}")) >> internet

finish(STEM)
