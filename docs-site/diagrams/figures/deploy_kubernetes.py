"""Kustomize. Message: the base runs the app; overlays bolt on everything else."""

from diagrams import Cluster, Edge
from kit import code, diagram, finish, group, icon, main_edge, opt_edge, titled

STEM = "deploy-kubernetes"

with diagram(STEM, nodesep="0.6", ranksep="0.9"):
    with Cluster(
        "base", graph_attr=titled("machine", "The base", "kubectl apply -k base", "tier basic")
    ):
        base = group(
            [
                ("Deployment", icon("si:kubernetes", "machine"), "ui on 8080"),
                ("Service", icon("mdi:lan-connect", "machine"), ":80"),
                ("PVCs", icon("mdi:harddisk", "machine"), "cache, output, models"),
                ("Secret", icon("mdi:key-variant", "machine"), "you create it"),
                ("NetworkPolicy", icon("mdi:shield-lock-outline", "machine")),
                ("CronJobs", icon("mdi:timer-outline", "machine"), "commented out"),
            ],
            cols=3,
        )
    with Cluster(
        "tiers", graph_attr=titled("network", "+ tier overlays", "overlays/tier-gpu, tier-full")
    ):
        tiers = group(
            [
                ("inference", icon("mdi:chip", "network"), code(":8092")),
                ("captioner", icon("mdi:closed-caption-outline", "network"), code(":8092/v1")),
                ("reader config", icon("mdi:robot-outline", "network"), "tier-full, egress 8000"),
            ],
            cols=3,
        )
    with Cluster(
        "comps",
        graph_attr=titled(
            "neutral", "+ components", "components/", "each patches the app pod", dashed=True
        ),
    ):
        comps = group(
            [
                ("gpu", icon("mdi:expansion-card", "neutral"), "one GPU on the app pod"),
                (
                    "render-sidecar",
                    icon("mdi:movie-open-cog-outline", "neutral"),
                    code(":8093") + " in the pod",
                ),
                (
                    "postgres",
                    icon("si:postgresql", "neutral"),
                    "a DATABASE_URL Secret,<br/>no server",
                ),
            ],
            cols=3,
        )

    base >> Edge(**main_edge(ltail="cluster_base", lhead="cluster_tiers", weight="10")) >> tiers
    base >> Edge(**opt_edge(ltail="cluster_base", lhead="cluster_comps")) >> comps

finish(STEM)
