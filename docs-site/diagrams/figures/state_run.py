"""A run's states. Message: a run is 'running' until it ends one of four ways."""

from diagrams import Cluster, Edge
from kit import (
    chips,
    code,
    diagram,
    finish,
    group,
    icon,
    main_edge,
    node,
    titled,
)

STEM = "state-run"

with diagram(STEM, nodesep="0.35", ranksep="0.6"):
    start = node(
        "start_run",
        icon("mdi:play-circle-outline", "machine"),
        px=44,
        sub="a " + code("pipeline_runs") + " row",
    )
    with Cluster(
        "running",
        graph_attr=titled("machine", "running", note="the phase moves along as the run works"),
    ):
        phases = chips(
            [
                "discovery",
                "download",
                "analysis",
                "selection",
                "render",
                "music",
                "delivery",
                "complete",
            ],
            per_row=4,
        )
    ends = group(
        [
            ("<b>completed</b>", icon("mdi:check-circle-outline", "keep"), code("complete_run")),
            ("<b>failed</b>", icon("mdi:close-circle-outline", "drop"), code("fail_run")),
            ("<b>cancelled</b>", icon("mdi:cancel", "neutral"), "Ctrl+C or the web Cancel"),
            (
                "<b>interrupted</b>",
                icon("mdi:restart-alert", "star"),
                "found running at server<br/>start, nobody holds the lock",
            ),
        ],
        cols=2,
        px=36,
    )

    start >> Edge(**main_edge(lhead="cluster_running")) >> phases
    phases >> Edge(**main_edge(ltail="cluster_running")) >> ends

finish(STEM)
