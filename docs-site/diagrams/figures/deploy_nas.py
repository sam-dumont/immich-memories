"""A NAS. Message: the same Compose file on every NAS; only the screen you paste it into changes."""

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

STEM = "deploy-nas"

with diagram(STEM, nodesep="0.55", ranksep="0.9"):
    browser = node("Your browser", icon("mdi:web", "neutral"), px=48, sub="port 8080")
    with Cluster("Your network", graph_attr=cluster("network")):
        with Cluster(
            "nas",
            graph_attr=titled(
                "machine",
                "Your NAS",
                "docker-compose.yml",
                "Synology, Unraid, TrueNAS or Portainer",
            ),
        ):
            app = node("<b>immich-memories</b>", icon("si:docker", "machine"), px=72, group="spine")
            folders = group(
                [
                    (
                        "config folder",
                        icon("mdi:harddisk", "machine"),
                        "config, SQLite store, cache",
                    ),
                    (
                        "output folder",
                        icon("mdi:folder-play-outline", "machine"),
                        "writable by UID 1000",
                    ),
                ],
                cols=2,
                px=40,
            )
        immich = node(
            "<b>Immich</b>",
            icon("mdi:image-album", "network"),
            px=72,
            group="spine",
            sub="on the NAS or elsewhere",
        )
        with Cluster(
            "box",
            graph_attr=titled(
                "optional", "Optional GPU box", "docker-compose.gpu-worker.yml", dashed=True
            ),
        ):
            box = node(
                "gpu-worker :8092",
                icon("mdi:expansion-card", "network"),
                px=48,
                sub=code("GPU_BOX")
                + ": facts, captions<br/>"
                + code("render.worker_base_url")
                + ": render",
            )

    browser >> Edge(**main_edge()) >> app
    app >> Edge(**main_edge(weight="20")) >> immich
    same_rank(app, folders)
    folders >> Edge(style="invis") >> app
    app >> Edge(**opt_edge(lhead="cluster_box")) >> box

finish(STEM)
