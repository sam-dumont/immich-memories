"""Docker Compose. Message: one container to start, one -f file per upgrade."""

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
                ("immich-memories", icon("si:docker", "machine"), code("127.0.0.1:8080")),
                ("config + store", icon("mdi:harddisk", "machine"), code("./output")),
            ],
            cols=2,
        )
    with tier("gpu", "network", "+ GPU tier: captions and checks", "docker-compose.gpu.yml"):
        gpu = group(
            [
                ("inference", icon("mdi:chip", "network"), code(":8092")),
                ("captioner", icon("mdi:closed-caption-outline", "network"), code(":8094")),
                ("caption models", icon("mdi:download", "network"), "one-shot download"),
            ]
        )
    with tier(
        "full", "neutral", "+ Full tier", "docker-compose.full.yml", "your reader model's URL"
    ):
        full = group([("Reader model", icon("mdi:robot-outline", "neutral"))])
    with tier(
        "cuda", "neutral", "+ CUDA images", "docker-compose.cuda.yml", "NVIDIA, one GPU each"
    ):
        cuda = group([("Accelerator", icon("mdi:expansion-card", "neutral"))])
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
        "outside",
        "Or: the GPU work on another machine",
        "docker-compose.gpu-worker.yml",
        "set GPU_BOX on the app; rendering takes its own URL",
        dashed=True,
    ):
        box = group(
            [("GPU box :8092", icon("mdi:expansion-card", "outside"), "facts, captions, render")]
        )

    # The documented -f order is one straight line: base, gpu, full, cuda.
    base >> Edge(**main_edge(ltail="cluster_base", lhead="cluster_gpu", weight="10")) >> gpu
    gpu >> Edge(**main_edge(ltail="cluster_gpu", lhead="cluster_full", weight="10")) >> full
    full >> Edge(**main_edge(ltail="cluster_full", lhead="cluster_cuda", weight="10")) >> cuda
    # Side options hang below the line: Postgres under the base, the GPU box under the tier it replaces.
    base >> Edge(**opt_edge(ltail="cluster_base", lhead="cluster_pg", minlen="1")) >> pg
    base >> Edge(**opt_edge(ltail="cluster_base", lhead="cluster_box")) >> box

finish(STEM)
