"""The web flow. Message: cut first, look at it, then render; nothing renders until you say so."""

from diagrams import Edge
from kit import code, diagram, finish, hue_edge, icon, main_edge, node, opt_edge, same_rank

STEM = "seq-web-job"


def stage(n, title, ico, sub):
    return node(f"<b>{n}  {title}</b>", ico, px=64, sub=sub, group="spine")


with diagram(STEM, nodesep="0.6", ranksep="0.5"):
    ask = stage(
        1, "Describe it", icon("mdi:form-select", "machine"), "pick the memory,<br/>press Cut"
    )
    cut = stage(
        2,
        "Cut",
        icon("mdi:content-cut", "machine"),
        code("generate --no-render") + "<br/>live progress",
    )
    sheet = stage(
        3, "Look", icon("mdi:view-grid-outline", "machine"), "a contact sheet<br/>of every shot"
    )
    render = stage(4, "Render", icon("si:ffmpeg", "machine"), code("runs render"))
    film = node(
        "<b>Your film</b>",
        icon("mdi:movie-check-outline", "keep"),
        px=64,
        group="spine",
        sub="play or download",
    )

    busy = node("busy", icon("mdi:timer-sand", "neutral"), px=36, sub="one job at a time")
    cancel = node("Cancel", icon("mdi:cancel", "drop"), px=36, sub="any time: stops the process")
    revise = node(
        "Revise", icon("mdi:swap-horizontal", "network"), px=36, sub="swap, drop, reorder shots"
    )
    upload = node(
        "Back into Immich",
        icon("mdi:cloud-upload-outline", "network"),
        px=36,
        sub="if you ticked upload",
    )

    chain = [ask, cut, sheet, render, film]
    for a, b in zip(chain, chain[1:], strict=False):
        a >> Edge(**main_edge(weight="20")) >> b
    same_rank(ask, busy)
    ask >> Edge(**hue_edge("neutral")) >> busy
    same_rank(cut, cancel)
    cut >> Edge(**hue_edge("drop")) >> cancel
    same_rank(sheet, revise)
    sheet >> Edge(**opt_edge(dir="both")) >> revise
    same_rank(film, upload)
    film >> Edge(**opt_edge()) >> upload

finish(STEM)
