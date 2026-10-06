"""The one look every docs diagram shares: palette, font, icon tiles, zones, edges.

Each script in figures/ imports from here and draws one diagram. build.py runs them,
once with THEME=light and once with THEME=dark. contribute/diagram-style.md has the rules.
"""

import base64
import json
import os
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).parent
BUILD = HERE / "build"
TILES = BUILD / "tiles"
FONTS = BUILD / "fonts"
OUT = pathlib.Path(os.environ.get("DIAGRAMS_OUT", BUILD / "out"))
ICONS = HERE / "icons.json"

THEME = os.environ.get("THEME", "light")
ICON_STYLE = os.environ.get("ICON_STYLE", "solid")
FONT = "Inter"
# Measured with DejaVu Sans Mono in the pinned image; browsers draw the stack in _FAMILIES.
MONO = "DejaVu Sans Mono"
_FAMILIES = {
    FONT: "Inter, Helvetica, Arial, sans-serif",
    MONO: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
}

# One hue per meaning. A reader learns "indigo = your machine" once and keeps it.
HUE = {
    "machine": "#4250AF",  # Immich primary
    "network": "#0D9488",  # teal
    "outside": "#EA580C",  # orange
    "neutral": "#64748B",  # slate
    "keep": "#16A34A",  # green
    "drop": "#DC2626",  # red
    "star": "#F59E0B",  # amber
}

if THEME == "dark":
    INK, MUTED = "#E5E7EB", "#9CA3AF"
    MAIN_EDGE, OPT_EDGE = "#E5E7EB", "#6B7280"
    FILL = {
        "machine": "#1B1F3B",
        "network": "#0B2B29",
        "optional": "#14181F",
        "outside": "#2B1709",
        "neutral": "#1A1E25",
        "keep": "#0E2416",
        "drop": "#2A1111",
        "star": "#2A2108",
    }
    BORDER = {
        "machine": "#5C6BD6",
        "network": "#14B8A6",
        "optional": "#4B5563",
        "outside": "#F97316",
        "neutral": "#4B5563",
        "keep": "#22C55E",
        "drop": "#EF4444",
        "star": "#F59E0B",
    }
    SOFT_FILL = {k: f"{v}33" for k, v in HUE.items()}
    SOFT_INK = {
        "machine": "#AAB4F0",
        "network": "#5EEAD4",
        "outside": "#FDBA74",
        "neutral": "#CBD5E1",
        "keep": "#86EFAC",
        "drop": "#FCA5A5",
        "star": "#FCD34D",
    }
else:
    INK, MUTED = "#1F2937", "#6B7280"
    MAIN_EDGE, OPT_EDGE = "#1F2937", "#9CA3AF"
    FILL = {
        "machine": "#EEF0FA",
        "network": "#EDFAF7",
        "optional": "#FFFFFF",
        "outside": "#FFF5ED",
        "neutral": "#F6F7F9",
        "keep": "#EFFAF2",
        "drop": "#FDF0F0",
        "star": "#FEF7E6",
    }
    BORDER = {
        "machine": "#C5CBEF",
        "network": "#9FE3D8",
        "optional": "#CBD5E1",
        "outside": "#FCC9A5",
        "neutral": "#D5DAE1",
        "keep": "#A7E3B9",
        "drop": "#F5B5B5",
        "star": "#F8D98A",
    }
    SOFT_FILL = {
        "machine": "#E3E6F7",
        "network": "#D5F5EF",
        "outside": "#FFE8D6",
        "neutral": "#E8ECF1",
        "keep": "#DAF5E2",
        "drop": "#FCE0E0",
        "star": "#FEF0C7",
    }
    SOFT_INK = HUE


# ---------------------------------------------------------------- icons


def _glyph(spec: str) -> tuple[str, float, float]:
    """Body, width and height of an Iconify icon. spec is 'mdi:chip' or 'si:svelte'."""
    entry = json.loads(ICONS.read_text())["icons"][spec]
    return entry["body"], entry["width"], entry["height"]


def icon(spec: str, zone: str) -> str:
    """A rounded tile with a monochrome glyph: the only icon shape in the kit. Returns an SVG path."""
    TILES.mkdir(parents=True, exist_ok=True)
    path = TILES / f"{ICON_STYLE}-{THEME}-{zone}-{spec.replace(':', '_')}.svg"
    if path.exists():
        return str(path)
    body, w, h = _glyph(spec)
    if ICON_STYLE == "soft":
        bg, fg = SOFT_FILL[zone], SOFT_INK[zone]
    else:
        bg, fg = HUE[zone], "#FFFFFF"
    scale = 132 / max(w, h)
    dx, dy = (256 - w * scale) / 2, (256 - h * scale) / 2
    body = re.sub(r'(fill|stroke)="(?!none)[^"]*"', rf'\1="{fg}"', body).replace("currentColor", fg)
    # Written aside and renamed: build.py renders figures in parallel and they share tiles.
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
        f'<rect x="4" y="4" width="248" height="248" rx="60" fill="{bg}"/>'
        f'<g transform="translate({dx:.1f} {dy:.1f}) scale({scale:.4f})" fill="{fg}" color="{fg}">{body}</g></svg>'
    )
    tmp.replace(path)
    return str(path)


# ---------------------------------------------------------------- graph pieces


def graph_attr(headline: str = "", sub: str = "", mono: bool = False, **extra) -> dict:
    """Graph attributes. The headline lives in the MDX component, so by default the SVG has none."""
    attrs = {
        "fontname": FONT,
        "fontcolor": INK,
        "bgcolor": "transparent",
        "pad": "0.3",
        "splines": "ortho",
        "nodesep": "0.5",
        "ranksep": "0.8",
        "compound": "true",
        "newrank": "true",
        "label": "",
    }
    if headline or sub:
        face = f' face="{MONO}"' if mono else ""
        rows = (
            f'<tr><td align="left"><font point-size="22"><b>{headline}</b></font></td></tr>'
            if headline
            else ""
        )
        rows += (
            f'<tr><td align="left"><font point-size="14" color="{MUTED}"{face}>{sub}</font></td></tr>'
            if sub
            else ""
        )
        attrs.update(
            labelloc="t",
            labeljust="l",
            label=f'<<table border="0" cellpadding="2" cellspacing="2">{rows}<tr><td> </td></tr></table>>',
        )
    attrs.update(extra)
    return attrs


NODE_ATTR = {
    "fontname": FONT,
    "fontsize": "14",
    "fontcolor": INK,
    "shape": "plaintext",
    "fixedsize": "false",
    "width": "0",
    "height": "0",
    "imagescale": "false",
}
EDGE_ATTR = {"fontname": FONT, "fontsize": "12", "fontcolor": MUTED, "arrowsize": "0.8"}


def cluster(zone: str, dashed: bool = False) -> dict:
    """A tinted, rounded zone. Dashed means 'only if you set it up'."""
    return {
        "style": "rounded,filled,dashed" if dashed else "rounded,filled",
        "fillcolor": FILL[zone],
        "color": BORDER[zone],
        "pencolor": BORDER[zone],
        "penwidth": "1.8",
        "fontname": FONT,
        "fontsize": "15",
        "fontcolor": INK,
        "labeljust": "l",
        "margin": "18",
    }


def titled(zone: str, title: str, code: str = "", note: str = "", dashed: bool = False) -> dict:
    """A zone with a bold title, then optionally a file or command in mono, then a short note."""
    attrs = cluster(zone, dashed=dashed)
    rows = f'<tr><td align="left"><b>{title}</b></td><td rowspan="3" width="14"> </td></tr>'
    if code:
        rows += f'<tr><td align="left"><font face="{MONO}" point-size="12" color="{MUTED}">{code}</font></td></tr>'
    if note:
        rows += (
            f'<tr><td align="left"><font point-size="12" color="{MUTED}">{note}</font></td></tr>'
        )
    attrs["label"] = f'<<table border="0" cellpadding="1" cellspacing="0">{rows}</table>>'
    return attrs


def main_edge(**kw) -> dict:
    """The path the message is about: bold and dark."""
    return {"color": MAIN_EDGE, "penwidth": "3", **kw}


def opt_edge(**kw) -> dict:
    """Anything you have to switch on: thin, dashed, grey."""
    return {"color": OPT_EDGE, "penwidth": "1.5", "style": "dashed", **kw}


def hue_edge(zone: str, dashed: bool = True, **kw) -> dict:
    return {"color": HUE[zone], "penwidth": "2", "style": "dashed" if dashed else "solid", **kw}


def _lines(text: str, size: int | None = None, color: str | None = None) -> str:
    """Label text as table rows, one line each.

    A line that holds any code() is set in mono from end to end. Mixing faces inside one line
    breaks in the browser: SVG drops the space where the font changes, and the two fonts are
    measured by Graphviz but drawn by the browser, so they collide. One face per line can't.
    """
    bold = text.startswith("<b>") and text.endswith("</b>")
    if bold:
        text = text[3:-4]
    rows = []
    for line in text.replace("\n", "<br/>").split("<br/>"):
        attrs = ""
        if _CODE_OPEN in line:
            attrs += f' face="{MONO}"'
            line = line.replace(_CODE_OPEN, "").replace(_CODE_CLOSE, "")
        if size:
            attrs += f' point-size="{size}"'
        if color:
            attrs += f' color="{color}"'
        body = f"<font{attrs}>{line}</font>" if attrs else line
        rows.append(f"<tr><td>{'<b>' + body + '</b>' if bold else body}</td></tr>")
    return f'<table border="0" cellspacing="0" cellpadding="1">{"".join(rows)}</table>'


def _cell(label: str, ico: str, px: int, sub: str = "") -> str:
    sub_row = f"<tr><td>{_lines(sub, 11, MUTED)}</td></tr>" if sub else ""
    return (
        '<table border="0" cellspacing="2" cellpadding="0">'
        f'<tr><td fixedsize="true" width="{px}" height="{px}"><img src="{ico}" scale="true"/></td></tr>'
        f"<tr><td>{_lines(label)}</td></tr>{sub_row}</table>"
    )


def node(label: str, ico: str, px: int = 56, sub: str = "", **attrs):
    """One icon tile with its label under it."""
    from diagrams import Node

    return Node(f"<{_cell(label, ico, px, sub)}>", shape="plaintext", margin="0", **attrs)


def group(items: list, cols: int = 3, px: int = 48, **attrs):
    """Several tiles in one node. Graphviz places one node far better than a column of siblings."""
    from diagrams import Node

    cells = [
        f'<td valign="top">{_cell(it[0], it[1], px, it[2] if len(it) > 2 else "")}</td>'
        for it in items
    ]
    rows = "".join(
        "<tr>" + "".join(cells[i : i + cols]) + "</tr>" for i in range(0, len(cells), cols)
    )
    return Node(
        f'<<table border="0" cellspacing="12" cellpadding="0">{rows}</table>>',
        shape="plaintext",
        margin="0",
        **attrs,
    )


def text_node(title: str, sub: str = "", zone: str = "neutral", **attrs):
    """A plain rounded pill, for outcomes and states that need no icon."""
    from diagrams import Node

    sub_row = f'<br/><font point-size="11" color="{MUTED}">{sub}</font>' if sub else ""
    return Node(
        f"<<b>{title}</b>{sub_row}>",
        shape="box",
        style="rounded,filled",
        fillcolor=FILL[zone],
        color=BORDER[zone],
        penwidth="1.5",
        margin="0.18,0.1",
        **attrs,
    )


def same_rank(*nodes) -> None:
    """Pin nodes into one column (LR) or one row (TB)."""
    from diagrams import getdiagram

    ids = "; ".join(f'"{n._id}"' for n in nodes)
    getdiagram().dot.body.append(f"{{rank=same; {ids}}}\n")


# ---------------------------------------------------------------- output


def diagram(stem: str, direction: str = "LR", **gattr):
    """Open a Diagram that writes out/<stem>[-dark].svg."""
    from diagrams import Diagram

    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "-dark" if THEME == "dark" else ""
    return Diagram(
        "",
        filename=str(OUT / f"{stem}{suffix}"),
        outformat="svg",
        show=False,
        direction=direction,
        graph_attr=graph_attr(**gattr),
        node_attr=NODE_ATTR,
        edge_attr=EDGE_ATTR,
    )


def _font_face() -> str:
    """The Inter weights the SVG uses, embedded: an SVG shown through <img> can't see the page's fonts."""
    faces = []
    for weight in (400, 700):
        woff2 = FONTS / f"inter-{weight}.woff2"
        if woff2.exists():
            data = base64.b64encode(woff2.read_bytes()).decode()
            faces.append(
                f"@font-face{{font-family:Inter;font-weight:{weight};"
                f"src:url(data:font/woff2;base64,{data}) format('woff2')}}"
            )
    return f"<style>{''.join(faces)}</style>" if faces else ""


def finish(stem: str) -> None:
    """Inline the tiles and the font, and make the SVG byte-stable. DIAGRAMS_PNG=1 adds a 2x review PNG."""
    suffix = "-dark" if THEME == "dark" else ""
    svg_path = OUT / f"{stem}{suffix}.svg"
    svg = svg_path.read_text()

    def _inline(m: re.Match) -> str:
        data = base64.b64encode(pathlib.Path(m.group(2)).read_bytes()).decode()
        return f'{m.group(1)}="data:image/svg+xml;base64,{data}"'

    svg = re.sub(r'(xlink:href|href)="(/[^"]+\.svg)"', _inline, svg)
    # diagrams gives nodes random ids; renumber them so the same input gives the same bytes.
    for i, old in enumerate(dict.fromkeys(re.findall(r"\b([0-9a-f]{32})\b", svg))):
        svg = svg.replace(old, f"n{i}")
    svg = re.sub(r"<!-- Generated by graphviz version [^>]*-->\n", "", svg)
    svg = re.sub(r"<!-- Title: [^>]*-->\n", "", svg)
    for name, stack in _FAMILIES.items():
        svg = re.sub(rf'font-family="{name}[^"]*"', f'font-family="{stack}"', svg)
    svg = re.sub(r"(<svg [^>]*>)", lambda m: m.group(1) + _font_face(), svg, count=1)
    svg_path.write_text(svg)
    if os.environ.get("DIAGRAMS_PNG"):
        bg = "#1B1B1D" if THEME == "dark" else "#FFFFFF"
        subprocess.run(
            [
                "rsvg-convert",
                "-z",
                "2",
                "-b",
                bg,
                "-o",
                str(svg_path.with_suffix(".png")),
                str(svg_path),
            ],
            check=True,
        )


def ladder(start, steps, end, exit_px: int = 40):
    """The kit's decision chart: checks on one straight line, each check's way out hanging under it.

    start/end: (label, icon, sub). steps: dicts with q, icon, and exit = (label, icon, sub, zone),
    or exit = a list of such tuples for a check with more than one way out.
    Reads left to right; the line is 'no, keep going', the drop is 'yes'.
    """
    from diagrams import Edge, getdiagram

    # Every ladder says the same thing about its arrows, in the same place.
    getdiagram().dot.graph_attr.update(
        labelloc="t",
        labeljust="l",
        label=f'<<font point-size="12" color="{MUTED}">&#8594; no, next check'
        "&#160;&#160;&#160;&#160;&#160;&#8595; yes</font>>",
    )
    prev = node(f"<b>{start[0]}</b>", start[1], px=56, sub=start[2], group="spine")
    for step in steps:
        check = node(
            f"<b>{step['q']}</b>", step["icon"], px=48, sub=step.get("sub", ""), group="spine"
        )
        prev >> Edge(**main_edge(weight="20")) >> check
        prev = check
        if "exit" not in step:
            continue
        exits = step["exit"] if isinstance(step["exit"], list) else [step["exit"]]
        if len(exits) == 1:
            label, ico, sub, zone = exits[0]
            out = node(label, ico, px=exit_px, sub=sub)
        else:
            out = group([(e[0], e[1], e[2]) for e in exits], cols=len(exits), px=exit_px)
            zone = exits[0][3]
        same_rank(check, out)
        check >> Edge(**hue_edge(zone)) >> out
    last = node(f"<b>{end[0]}</b>", end[1], px=64, sub=end[2], group="spine")
    prev >> Edge(**main_edge(weight="20")) >> last
    return last


_CODE_OPEN, _CODE_CLOSE = "\x01", "\x02"


def code(text: str) -> str:
    """Mark a setting, path or command. The whole line it sits on is set in mono (see _lines)."""
    return f"{_CODE_OPEN}{text}{_CODE_CLOSE}"


def chips(words: list, zone: str = "machine", per_row: int = 4, **attrs):
    """A row (or rows) of rounded chips joined by arrows: a sequence that needs no icons."""
    from diagrams import Node

    def chip(w):
        return (
            f'<td style="rounded" border="1" color="{BORDER[zone]}" bgcolor="{FILL[zone]}" '
            f'cellpadding="7">{w}</td>'
        )

    arrow = f'<td><font color="{MUTED}">&#8594;</font></td>'
    rows = []
    for start in range(0, len(words), per_row):
        chunk = words[start : start + per_row]
        row = []
        for i, w in enumerate(chunk):
            row.append(chip(w))
            if start + i < len(words) - 1:
                row.append(arrow)
        rows.append(row)
    body = "".join("<tr>" + "".join(r) + "</tr>" for r in rows)
    return Node(
        f'<<table border="0" cellspacing="6" cellpadding="2">{body}</table>>',
        shape="plaintext",
        margin="0",
        **attrs,
    )


def text_label(text: str, **attrs):
    """Words that sit on a line: the line passes through this node instead of carrying a label."""
    from diagrams import Node

    return Node(
        f'<<font point-size="12" color="{MUTED}">{text}</font>>',
        shape="plaintext",
        margin="0.05",
        **attrs,
    )
