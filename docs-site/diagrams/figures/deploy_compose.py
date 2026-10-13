"""Docker Compose: Basic is one container; GPU adds services, Full connects a reader."""

from diagrams import Cluster, Edge
from kit import code, diagram, finish, group, icon, main_edge, opt_edge, titled

STEM = "deploy-compose"


def tier(cid, zone, title, file, note="", dashed=False):
    return Cluster(cid, graph_attr=titled(zone, title, file, note, dashed=dashed))


with diagram(STEM, nodesep="0.6", ranksep="0.9"):
    with tier(
        "base", "machine", "Basic: the whole app", "docker-compose.yml", "CPU, rules, up to 1080p"
    ):
        base = group(
            [
                ("immich-memories", icon("si:docker", "machine"), "host port → container :8080"),
                ("config + store", icon("mdi:harddisk", "machine"), "named config volume"),
                ("Films", icon("mdi:folder-play-outline", "machine"), code("./output")),
            ],
            cols=3,
        )
    with tier(
        "gpu",
        "network",
        "+ GPU tier: captions and checks",
        "docker-compose.gpu.yml<br/>docker-compose.cuda.yml",
        "NVIDIA driver and Container Toolkit",
    ):
        gpu = group(
            [
                ("inference", icon("mdi:chip", "network"), "container + host :8092"),
                (
                    "captioner",
                    icon("mdi:closed-caption-outline", "network"),
                    "container :8092, host :8094",
                ),
                ("caption models", icon("mdi:download", "network"), "one-shot download"),
            ]
        )
    with tier(
        "full",
        "neutral",
        "+ Full tier",
        "docker-compose.full.yml",
        "connect and enable your reader",
    ):
        full = group(
            [("Existing reader", icon("mdi:robot-outline", "neutral"), "URL + served model")]
        )
    with tier(
        "pg",
        "neutral",
        "+ PostgreSQL, any tier",
        "docker-compose.postgres.yml",
        "the store moves off SQLite",
        dashed=True,
    ):
        pg = group([("postgres:16", icon("si:postgresql", "neutral"), "no published port")])
    with tier(
        "box",
        "network",
        "Or: GPU work on another private machine",
        "docker-compose.gpu-worker.yml",
        "set GPU_BOX on the app; rendering takes its own URL",
        dashed=True,
    ):
        box = group(
            [("GPU box :8092", icon("mdi:expansion-card", "network"), "facts, captions, render")]
        )

    # GPU needs both overlays; Full only adds the existing reader connection.
    base >> Edge(**main_edge(ltail="cluster_base", lhead="cluster_gpu", weight="10")) >> gpu
    gpu >> Edge(**main_edge(ltail="cluster_gpu", lhead="cluster_full", weight="10")) >> full
    # Side options hang below the line: Postgres under the base, the GPU box under the tier it replaces.
    base >> Edge(**opt_edge(ltail="cluster_base", lhead="cluster_pg", minlen="1")) >> pg
    base >> Edge(**opt_edge(ltail="cluster_base", lhead="cluster_box")) >> box

finish(STEM)
