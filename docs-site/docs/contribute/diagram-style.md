---
title: Diagram style
sidebar_position: 9
---

# Diagram style

Diagrams come from the code, not from memory. Each one is a Mermaid block placed with a marker
comment (`{/* diagram: <name> */}`) so it can be regenerated without hunting through prose.

| Question | Diagram |
|---|---|
| What are the parts and what talks to what? | architecture (components, and what crosses the network boundary) |
| What runs where for my install? | deployment, one per install path |
| What happens, in order, when I run X? | sequence (`generate`, a scheduled run, `--ask`, a web job) |
| Which option should I pick? / Why was this picture kept? | decision chart |
| What states can a run be in? | state diagram |

Check a new or changed block renders with `make docs-build` before pushing; the writing-docs gates
cover voice and drift, not Mermaid syntax.
