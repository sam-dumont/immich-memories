"""What `generate` does. Message: five steps from library to film; tiers only add helpers."""

from diagrams import Edge
from kit import diagram, finish, hue_edge, icon, main_edge, node, opt_edge, same_rank

STEM = "seq-generate"


def stage(n, title, ico, sub):
    return node(f"<b>{n}  {title}</b>", ico, px=64, sub=sub, group="spine")


with diagram(STEM, nodesep="0.6", ranksep="0.5"):
    read = stage(
        1, "Read", icon("mdi:image-album", "network"), "people, photos and videos<br/>in the period"
    )
    look = stage(
        2,
        "Look",
        icon("mdi:image-search-outline", "machine"),
        "previews, faces, pixel facts;<br/>drops screenshots, copies",
    )
    pick = stage(
        3,
        "Choose",
        icon("mdi:movie-filter-outline", "machine"),
        "stories, best shots,<br/>family-viewing check, length",
    )
    dress = stage(
        4,
        "Title + music",
        icon("mdi:music-box-outline", "machine"),
        "your title or a template;<br/>your track, generated or bundled",
    )
    render = stage(
        5,
        "Render",
        icon("si:ffmpeg", "machine"),
        "FFmpeg cuts clips,<br/>titles and music together",
    )
    film = node(
        "<b>Your film</b>",
        icon("mdi:movie-check-outline", "keep"),
        px=64,
        group="spine",
        sub="in your output folder",
    )

    captions = node(
        "Captions + checks",
        icon("mdi:closed-caption-outline", "network"),
        px=40,
        sub="GPU and Full tiers",
    )
    reader = node(
        "Reader model",
        icon("mdi:robot-outline", "network"),
        px=40,
        sub="Full tier reads the period",
    )
    nothing = node(
        "Nothing worth a film",
        icon("mdi:close-circle-outline", "drop"),
        px=40,
        sub="no film, exit 0",
    )
    worker = node(
        "Render worker", icon("mdi:expansion-card", "network"), px=40, sub="if you set one up"
    )
    upload = node(
        "Back into Immich",
        icon("mdi:cloud-upload-outline", "network"),
        px=40,
        sub="if upload is on",
    )

    read >> Edge(**main_edge(weight="20")) >> look >> Edge(**main_edge(weight="20")) >> pick
    pick >> Edge(**main_edge(weight="20")) >> dress >> Edge(**main_edge(weight="20")) >> render
    render >> Edge(**main_edge(weight="20")) >> film
    for step, helper in ((look, captions), (pick, reader), (render, worker)):
        same_rank(step, helper)
        helper >> Edge(**opt_edge()) >> step
    same_rank(film, upload)
    film >> Edge(**opt_edge()) >> upload
    same_rank(dress, nothing)
    pick >> Edge(**hue_edge("drop")) >> nothing

finish(STEM)
