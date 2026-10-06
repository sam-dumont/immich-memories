"""What a film run can call. Message: every helper is one setting, and none is on until you set it."""

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

STEM = "architecture-detailed-2"
BOX = "box"

with diagram(STEM, nodesep="0.5", ranksep="0.9"):
    with Cluster("Your network", graph_attr=cluster("network")):
        with Cluster("Your app host", graph_attr=cluster("machine")):
            gen = node(
                "<b>Film run</b>",
                icon("mdi:movie-open-play", "machine"),
                px=72,
                group="spine",
                sub="generate",
            )
            onhost = group(
                [
                    (
                        "llama-server reader",
                        icon("mdi:robot-outline", "machine"),
                        code("llm.enabled, blank base_url"),
                    ),
                    (
                        "ACE-Step, lib mode",
                        icon("mdi:music-note", "machine"),
                        code("ace_step.mode: lib"),
                    ),
                ],
                cols=2,
                px=40,
            )
        immich = node(
            "<b>Immich API</b>",
            icon("mdi:image-album", "network"),
            px=72,
            group="spine",
            sub="API key: reads;<br/>writes only with upload on",
        )
        with Cluster(
            BOX,
            graph_attr=titled("optional", "GPU box or service pods", note="optional", dashed=True),
        ):
            box = group(
                [
                    (
                        "Inference :8092",
                        icon("mdi:chip", "network"),
                        code("inference.facts_base_url"),
                    ),
                    (
                        "Captions :8092/v1",
                        icon("mdi:closed-caption-outline", "network"),
                        code("caption_base_url"),
                    ),
                    (
                        "Render worker",
                        icon("mdi:movie-open-cog-outline", "network"),
                        code("render.worker_base_url"),
                    ),
                ],
                cols=3,
                px=40,
            )
        with Cluster(
            "lan",
            graph_attr=titled("optional", "Other services you run", note="optional", dashed=True),
        ):
            lan = group(
                [
                    ("Reader model", icon("mdi:robot-outline", "network"), code("llm.base_url")),
                    ("ACE-Step API", icon("mdi:music-note", "network"), code("ace_step.api_url")),
                ],
                cols=2,
                px=40,
            )

    gen >> Edge(**main_edge(weight="20")) >> immich
    same_rank(gen, onhost)
    onhost >> Edge(style="invis") >> gen
    gen >> Edge(**opt_edge()) >> onhost
    gen >> Edge(**opt_edge(lhead=f"cluster_{BOX}")) >> box
    gen >> Edge(**opt_edge(lhead="cluster_lan")) >> lan

finish(STEM)
