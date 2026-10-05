"""Inside the app host. Message: every way in ends in the same film run."""

from diagrams import Cluster, Edge
from kit import cluster, diagram, finish, group, icon, main_edge, node, opt_edge, titled

STEM = "architecture-detailed"

with diagram(STEM, nodesep="0.5", ranksep="0.7"):
    browser = node("Browser", icon("mdi:web", "neutral"), px=48)
    with Cluster("Your app host", graph_attr=cluster("machine")):
        with Cluster(
            "server",
            graph_attr=titled("optional", "Web server process", "immich-memories ui, port 8080"),
        ):
            api = node(
                "FastAPI", icon("si:fastapi", "machine"), px=48, sub="/app, /api/v1, /api/trigger"
            )
            timer = node(
                "In-process timer", icon("mdi:timer-outline", "machine"), px=48, sub="once a day"
            )
            jobs = node(
                "Job runner",
                icon("mdi:format-list-checks", "machine"),
                px=48,
                sub="one job at a time",
            )
            runner = node(
                "Automation runner",
                icon("mdi:robot-industrial-outline", "machine"),
                px=48,
                sub="lease, cooldown, what's due",
            )
        with Cluster(
            "os", graph_attr=titled("optional", "Or an OS timer", "auto install", dashed=True)
        ):
            ostimer = node("launchd, systemd, cron", icon("mdi:calendar-clock", "machine"), px=48)
            autorun = node(
                "auto run", icon("mdi:console", "machine"), px=48, sub="the same runner, as a CLI"
            )
        gen = node(
            "<b>Film run</b>",
            icon("mdi:movie-open-play", "machine"),
            px=72,
            group="spine",
            sub="generate, or runs render",
        )
        local = group(
            [
                ("FFmpeg", icon("si:ffmpeg", "machine")),
                ("Store", icon("mdi:database", "machine"), "SQLite or PostgreSQL"),
                ("Films, caches,\nlogs", icon("mdi:harddisk", "machine")),
            ],
            cols=1,
            px=40,
        )

    browser >> Edge(**main_edge()) >> api
    api >> Edge(**main_edge()) >> jobs
    api >> Edge(**opt_edge()) >> runner
    timer >> Edge(**main_edge()) >> runner
    ostimer >> Edge(**opt_edge()) >> autorun
    jobs >> Edge(**main_edge()) >> gen
    runner >> Edge(**main_edge()) >> gen
    autorun >> Edge(**opt_edge()) >> gen
    gen >> Edge(**main_edge(weight="10")) >> local

finish(STEM)
