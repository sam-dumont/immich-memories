"""generate, with the code's names. Message: the same five steps, and where each one writes its trace."""

from diagrams import Edge
from kit import code, diagram, finish, hue_edge, icon, main_edge, node, opt_edge, same_rank

STEM = "seq-generate-reference"


def stage(n, title, ico, sub):
    return node(f"<b>{n}  {title}</b>", ico, px=56, sub=sub, group="spine")


with diagram(STEM, direction="TB", nodesep="0.6", ranksep="0.35"):
    start = stage(
        0,
        "Start",
        icon("mdi:console", "machine"),
        code("load_config")
        + "<br/>"
        + code("RunTracker.start_run")
        + "<br/>run blockers: encoder, output dir",
    )
    read = stage(
        1,
        "Read",
        icon("mdi:image-album", "network"),
        code("GET /people") + "<br/>" + code("POST /search/metadata"),
    )
    look = stage(
        2,
        "Prepare",
        icon("mdi:image-search-outline", "machine"),
        "thumbnails, faces, OCR,<br/>pixel facts, heads",
    )
    pick = stage(
        3,
        "Select",
        icon("mdi:movie-filter-outline", "machine"),
        code("plan_structure")
        + ", "
        + code("_select")
        + ":<br/>stories, admission, audience gate,<br/>timing, duplicate review",
    )
    dress = stage(
        4,
        "Title + music",
        icon("mdi:music-box-outline", "machine"),
        code("resolve_film_title") + "<br/>ACE-Step, MusicGen, bundled",
    )
    render = stage(
        5,
        "Render",
        icon("si:ffmpeg", "machine"),
        code("PipelineLock") + "<br/>" + code("VideoAssembler") + " + titles<br/>decode check",
    )
    done = node(
        "<b>complete_run</b>",
        icon("mdi:database-check-outline", "keep"),
        px=56,
        group="spine",
        sub=code("pipeline_runs") + ", " + code("run_attempts"),
    )

    gpu = node(
        "detectors, captions",
        icon("mdi:closed-caption-outline", "network"),
        px=36,
        sub=code("facts_base_url") + "<br/>" + code("caption_base_url"),
    )
    trace = node(
        "selection trace",
        icon("mdi:file-document-outline", "neutral"),
        px=36,
        sub=code("editorial_verdicts") + "<br/>" + code("audience_holds"),
    )
    nothing = node(
        "Nothing worth a film", icon("mdi:close-circle-outline", "drop"), px=36, sub="exit 0"
    )
    worker = node(
        "render worker",
        icon("mdi:expansion-card", "network"),
        px=36,
        sub=code("POST /jobs") + ", poll",
    )
    upload = node(
        "upload",
        icon("mdi:cloud-upload-outline", "network"),
        px=36,
        sub=code("POST /assets") + ", tag, album",
    )

    chain = [start, read, look, pick, dress, render, done]
    for a, b in zip(chain, chain[1:], strict=False):
        a >> Edge(**main_edge(weight="20")) >> b
    for step, helper in ((look, gpu), (render, worker)):
        same_rank(step, helper)
        step >> Edge(**opt_edge(dir="back")) >> helper
    same_rank(pick, trace)
    pick >> Edge(**opt_edge()) >> trace
    same_rank(dress, nothing)
    pick >> Edge(**hue_edge("drop")) >> nothing
    same_rank(done, upload)
    done >> Edge(**opt_edge()) >> upload

finish(STEM)
