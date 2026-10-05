"""Render every figure, light and dark, into docs-site/static/diagrams/ (or check they're current).

    python docs-site/diagrams/build.py            # write the SVGs
    python docs-site/diagrams/build.py --check    # fail if a committed SVG is stale

Run it through `make docs-diagrams` / `make docs-diagrams-check`: they use the pinned image in
this folder, because Graphviz lays out differently from one version to the next.
"""

import argparse
import concurrent.futures
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
SITE = HERE.parent
BUILD = HERE / "build"
FONTS = BUILD / "fonts"
COMMITTED = SITE / "static" / "diagrams"
THEMES = ("light", "dark")
# Everything a diagram label can contain; the embedded font carries only these glyphs.
GLYPHS = "".join(chr(c) for c in range(0x20, 0x7F)) + "“”‘’…→×–é"


def prepare_fonts() -> pathlib.Path:
    """Inter from the site's own woff2: a TTF for Graphviz to measure with, and two small subsets to embed."""
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    FONTS.mkdir(parents=True, exist_ok=True)
    source = TTFont(SITE / "static" / "fonts" / "inter-latin.woff2")
    source.flavor = None
    source.save(FONTS / "Inter.ttf")
    for weight in (400, 700):
        font = instancer.instantiateVariableFont(TTFont(FONTS / "Inter.ttf"), {"wght": weight})
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["kern", "liga"]
        subsetter = subset.Subsetter(options)
        subsetter.populate(text=GLYPHS)
        subsetter.subset(font)
        font.flavor = "woff2"
        # A fresh timestamp would change every SVG on every run.
        font.recalcTimestamp = False
        font["head"].modified = font["head"].created
        font.save(FONTS / f"inter-{weight}.woff2")
    conf = FONTS / "fonts.conf"
    conf.write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
        '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
        '  <include ignore_missing="yes">/opt/homebrew/etc/fonts/fonts.conf</include>\n'
        f"  <dir>{FONTS}</dir>\n  <cachedir>{BUILD / 'fontcache'}</cachedir>\n</fontconfig>\n"
    )
    return conf


def render(figure: pathlib.Path, theme: str, out: pathlib.Path, conf: pathlib.Path) -> str:
    env = {
        **os.environ,
        "THEME": theme,
        "DIAGRAMS_OUT": str(out),
        "FONTCONFIG_FILE": str(conf),
        "PYTHONPATH": str(HERE),
    }
    result = subprocess.run(
        [sys.executable, str(figure)], env=env, capture_output=True, text=True, cwd=HERE
    )
    if result.returncode:
        return f"{figure.name} ({theme}) failed:\n{result.stderr}"
    return ""


def build(out: pathlib.Path) -> None:
    conf = prepare_fonts()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.svg"):
        old.unlink()
    figures = sorted((HERE / "figures").glob("*.py"))
    jobs = [(f, t) for f in figures for t in THEMES]
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        errors = [e for e in pool.map(lambda job: render(job[0], job[1], out, conf), jobs) if e]
    if errors:
        sys.exit("\n".join(errors))
    print(f"{len(jobs)} diagrams in {out}")


def check() -> None:
    fresh = BUILD / "check"
    shutil.rmtree(fresh, ignore_errors=True)
    build(fresh)
    made = {p.name for p in fresh.glob("*.svg")}
    kept = {p.name for p in COMMITTED.glob("*.svg")}
    stale = sorted(
        n for n in made & kept if (fresh / n).read_bytes() != (COMMITTED / n).read_bytes()
    )
    problems = [f"stale: {n}" for n in stale]
    problems += [f"missing: {n}" for n in sorted(made - kept)]
    problems += [f"no figure makes it: {n}" for n in sorted(kept - made)]
    if problems:
        print("\n".join(problems))
        sys.exit(
            "docs-site/static/diagrams is out of date: run 'make docs-diagrams' and commit the result"
        )
    print(f"all {len(made)} diagrams are current")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a committed SVG is stale")
    args = parser.parse_args()
    check() if args.check else build(COMMITTED)
