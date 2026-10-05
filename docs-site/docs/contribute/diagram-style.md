---
title: Diagram style
description: How the docs draw diagrams, while the diagram tool is being redone.
---

# Diagram style

The docs previously shipped a set of shared Mermaid diagrams with bundled icon packs and an ELK
layout. That kit is being replaced, so the shared diagrams and their icon/layout dependencies
are removed for now. Pages that want a diagram carry a `{/* diagram: NAME */}` marker instead of
a wired-up import; nothing renders there yet.

A few simple, page-local `mermaid` flowchart blocks remain where they already existed (for
example in [How it chooses](../how-it-chooses/overview.md) and
[Titles, maps and music](../make/titles-maps-music.md)), since they need no icons or special
layout. The zoom and fit-width behaviour in the Mermaid theme component still applies to those.

This page will describe the new diagram style once the replacement tool is in place.
