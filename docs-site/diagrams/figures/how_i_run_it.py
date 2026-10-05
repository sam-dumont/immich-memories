"""The owner's own setup. Message: one CPU pod runs the app; one shared GPU does the heavy lifting."""

from diagrams import Cluster, Edge
from kit import (
    cluster,
    code,
    diagram,
    finish,
    group,
    hue_edge,
    icon,
    main_edge,
    node,
    opt_edge,
    titled,
)

STEM = "how-i-run-it"

with diagram(STEM, nodesep="0.5", ranksep="0.8"):
    browser = node("Browser", icon("mdi:web", "neutral"), px=44, sub="TLS proxy, OIDC login")
    with Cluster("Your network", graph_attr=cluster("network")):
        with Cluster("k8s", graph_attr=titled("optional", "Kubernetes cluster")):
            with Cluster("cpu", graph_attr=titled("machine", "CPU node")):
                app = node(
                    "<b>immich-memories</b>",
                    icon("mdi:movie-open-play", "machine"),
                    px=64,
                    group="spine",
                    sub="one pod: web UI, selection,<br/>family-viewing check, store",
                )
            with Cluster("gpu", graph_attr=titled("network", "GPU node, 8 GB, time-sliced")):
                gpu = group(
                    [
                        (
                            "GPU worker",
                            icon("mdi:expansion-card", "network"),
                            code(":8092") + " captions, classifiers,<br/>stems, render",
                        ),
                        ("ACE-Step API", icon("mdi:music-note", "network"), "music"),
                        ("Immich ML", icon("mdi:brain", "network"), "shares the card"),
                    ],
                    cols=3,
                    px=40,
                )
            immich = node("<b>Immich</b>", icon("mdi:image-album", "network"), px=64, group="spine")
            with Cluster(
                "spare",
                graph_attr=titled(
                    "optional",
                    "Older GPU node",
                    note="standby caption server,<br/>scaled to zero",
                    dashed=True,
                ),
            ):
                spare = node("caption server", icon("mdi:expansion-card", "neutral"), px=40)
        with Cluster("mac", graph_attr=titled("optional", "A Mac on the LAN", dashed=True)):
            mac = node(
                "Reader model", icon("si:apple", "machine"), px=44, sub="a small local model"
            )
    with Cluster("net", graph_attr=titled("outside", "The internet, switched on", dashed=True)):
        out = group(
            [
                ("Place names", icon("mdi:map-marker-radius-outline", "outside")),
                ("Map tiles", icon("mdi:map-outline", "outside")),
                ("Notifications", icon("mdi:bell-ring-outline", "outside")),
            ],
            cols=3,
            px=36,
        )

    browser >> Edge(**main_edge()) >> app
    app >> Edge(**main_edge(weight="20")) >> immich
    app >> Edge(**main_edge(lhead="cluster_gpu")) >> gpu
    gpu >> Edge(**opt_edge(ltail="cluster_gpu", xlabel="")) >> immich
    app >> Edge(**opt_edge(lhead="cluster_spare")) >> spare
    app >> Edge(**opt_edge(lhead="cluster_mac")) >> mac
    app >> Edge(**hue_edge("outside", lhead="cluster_net")) >> out

finish(STEM)
