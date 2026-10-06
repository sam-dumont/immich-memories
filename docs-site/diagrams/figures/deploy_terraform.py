"""Terraform module. Message: it creates the app's own objects; cron, policy and Postgres are yours."""

from diagrams import Cluster, Edge
from kit import code, diagram, finish, group, icon, main_edge, node, opt_edge, titled

STEM = "deploy-terraform"

with diagram(STEM, nodesep="0.6", ranksep="0.9"):
    tf = node(
        "<b>terraform apply</b>", icon("si:terraform", "machine"), px=64, sub="kubernetes provider"
    )
    with Cluster("made", graph_attr=titled("machine", "Created in your cluster", note="tier auto")):
        made = group(
            [
                ("Namespace", icon("si:kubernetes", "machine"), code("create_namespace")),
                (
                    "Secret",
                    icon("mdi:key-variant", "machine"),
                    "unless " + code("existing_secret_name"),
                ),
                (
                    "Deployment",
                    icon("mdi:movie-open-play", "machine"),
                    "optional GPU,<br/>render sidecar",
                ),
                ("Service", icon("mdi:lan-connect", "machine"), ":80"),
                ("PVCs", icon("mdi:harddisk", "machine"), "output, cache, models"),
                ("Ingress", icon("mdi:web", "machine"), code("ingress_enabled")),
                (
                    "Captioner",
                    icon("mdi:closed-caption-outline", "machine"),
                    code("captioner_enabled"),
                ),
            ],
            cols=4,
        )
    with Cluster(
        "notmade", graph_attr=titled("neutral", "Not created: add them yourself", dashed=True)
    ):
        notmade = group(
            [
                ("CronJob", icon("mdi:timer-outline", "neutral")),
                ("NetworkPolicy", icon("mdi:shield-lock-outline", "neutral")),
                ("Inference service", icon("mdi:chip", "neutral")),
                ("PostgreSQL", icon("si:postgresql", "neutral")),
            ],
            cols=2,
        )

    tf >> Edge(**main_edge(lhead="cluster_made", weight="10")) >> made
    (
        made
        >> Edge(
            **opt_edge(
                ltail="cluster_made", lhead="cluster_notmade", arrowhead="none", style="invis"
            )
        )
        >> notmade
    )

finish(STEM)
