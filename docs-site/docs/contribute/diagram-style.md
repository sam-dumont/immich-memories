---
title: Diagram style
description: How the docs diagrams are drawn, the rules they follow, and how to add one.
---

# Diagram style

Every diagram in these docs is a short Python script in `docs-site/diagrams/figures/`, drawn with
[diagrams](https://diagrams.mingrammer.com/) on top of Graphviz. `make docs-diagrams` renders each
script twice (light and dark) into `docs-site/static/diagrams/`, and the SVGs are committed, so
building the site never needs Graphviz. CI runs `make docs-diagrams-check`, which fails when a
committed SVG no longer matches its script.

Both targets run in the pinned image in `docs-site/diagrams/Dockerfile` (Graphviz 12.2.1 on
Alpine 3.24). Graphviz moves boxes around between releases, so a diagram drawn with your local
Graphviz won't match the one CI draws. You need Docker; nothing else.

A few small page-local `mermaid` blocks remain where they already existed (for example in
[Photos and Live Photos](../make/photos-and-live-photos.md)). New diagrams use the kit below.

## One diagram, one message

A diagram says one thing, and that thing is its headline: one or two short sentences in the same
voice as the rest of the docs, shown above the picture. "Start with one container. Add a file
for each upgrade." is a headline. "Docker Compose deployment" is a caption, not a headline.

If the headline needs an "and also", draw two diagrams.

## The rules

- **It reads left to right.** The main path is one straight, bold, dark line. Long reference
  pipelines may run top to bottom instead, so the text stays readable.
- **Optional is dashed and grey.** Anything you have to switch on (a GPU box, a reader model, an
  internet service) hangs off the main line with a thin dashed edge, inside a dashed zone.
- **One hue per meaning, everywhere.** Indigo is your machine, teal is your network, orange is
  the internet, slate is neutral, green is the result you want, red is dropped or failed, gold is
  a favourite. Never use a hue for decoration.
- **One icon shape.** Every icon is the same rounded tile: the hue fills it, the glyph is white.
  Brands get their monochrome glyph on a tile like everything else. Two exceptions: no Immich
  logo (it's Immich's trademark, so Immich is a photo-album glyph), and no GPU vendor logo (a GPU
  is "GPU box" or "accelerator", whoever made it).
- **Labels are short.** A name, then at most two short lines under it. Settings, paths and
  commands are in mono. Edges carry no labels (Graphviz puts them on top of the line): the words
  go on the node or on the zone's title.
- **Decisions are a ladder.** The checks sit on one line, and each check's way out hangs under
  it, in red (dropped), gold (gets through) or green (the outcome). No diamond flowcharts.
- **No private data.** No names, places, dates or library numbers from a real library.

## Add a diagram

1. Copy the closest script in `figures/` (`deploy_nas.py` for a deployment, `decide_tier.py` for
   a decision, `seq_generate.py` for a pipeline) and rename it. Its `STEM` constant is the name
   the page uses.
2. Draw with the kit in `diagrams/kit.py`: `node()` for one tile, `group()` for several tiles in
   one box (Graphviz places one node far better than a column of siblings), `titled()` for a
   zone, `main_edge()` and `opt_edge()` for edges, `ladder()` for a decision chart.
3. Icons are named `mdi:<name>` ([Material Design Icons](https://pictogrammers.com/library/mdi/))
   or `si:<name>` ([Simple Icons](https://simpleicons.org/)). A new one goes into `icons.json`:
   install the two Iconify sets and run `vendor_icons.py`, as its docstring says.
4. Run `make docs-diagrams` and look at the SVG, light and dark. Fix crossings and long detours
   before you commit, usually with `same_rank()`, a `group()`, or by moving a helper under the
   step it helps.
5. Put it on a page, on its own line:

   ```mdx
   <Diagram name="deploy-nas" headline="Every NAS runs the same Compose file. Only the screen you paste it into changes." />
   ```

   `Diagram` needs no import. It shows the headline, picks the light or dark SVG, and opens the
   diagram full screen when clicked. The headline is also the image's alt text.
6. Commit the script and both SVGs together. `make docs-diagrams-check` must pass.
