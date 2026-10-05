"""Every outbound call. Message: only Immich is always on; everything else waits for a setting."""

from diagrams import Cluster, Edge
from kit import cluster, code, diagram, finish, group, hue_edge, icon, main_edge, node, opt_edge

STEM = "privacy-map"
LAN = "lan"
OUT = "out"

with diagram(STEM, nodesep="0.5", ranksep="1.0"):
    with Cluster("Your app host", graph_attr=cluster("machine")):
        app = node(
            "<b>immich-memories</b>", icon("mdi:movie-open-play", "machine"), px=72, group="spine"
        )
    with Cluster("Your network", graph_attr=cluster("network")):
        immich = node(
            "<b>Immich</b>",
            icon("mdi:image-album", "network"),
            px=64,
            group="spine",
            sub="always: reads<br/>upload.enabled: writes",
        )
        with Cluster(
            LAN, graph_attr=cluster("optional", dashed=True) | {"label": "Your own services"}
        ):
            lan = group(
                [
                    (
                        "Reader model",
                        icon("mdi:robot-outline", "network"),
                        code("llm.base_url") + ", text only",
                    ),
                    (
                        "Caption server",
                        icon("mdi:closed-caption-outline", "network"),
                        code("caption_base_url") + ", 400 px tiles",
                    ),
                    ("Inference", icon("mdi:chip", "network"), code("inference.facts_base_url")),
                    (
                        "Render worker",
                        icon("mdi:movie-open-cog-outline", "network"),
                        code("render.worker_base_url"),
                    ),
                    ("Music API", icon("mdi:music-note", "network"), code("ace_step.api_url")),
                ],
                cols=3,
                px=40,
            )
    with Cluster(
        OUT,
        graph_attr=cluster("outside", dashed=True) | {"label": "The internet: all off by default"},
    ):
        out = group(
            [
                (
                    "Hosted reader",
                    icon("mdi:cloud-outline", "outside"),
                    "llm.provider: openai,<br/>anthropic, zai",
                ),
                (
                    "Place names",
                    icon("mdi:map-marker-radius-outline", "outside"),
                    code("network.geocoding"),
                ),
                ("Map tiles", icon("mdi:map-outline", "outside"), code("network.map_tiles")),
                (
                    "Notifications",
                    icon("mdi:bell-ring-outline", "outside"),
                    code("notifications.enabled"),
                ),
                ("Login provider", icon("si:openid", "outside"), code("auth.provider: oidc")),
                (
                    "Model downloads",
                    icon("si:huggingface", "outside"),
                    "models fetch,<br/>allow_model_downloads",
                ),
            ],
            cols=3,
            px=40,
        )

    app >> Edge(**main_edge(weight="20")) >> immich
    app >> Edge(**opt_edge(lhead=f"cluster_{LAN}")) >> lan
    app >> Edge(**hue_edge("outside", lhead=f"cluster_{OUT}")) >> out

finish(STEM)
