# The renderer for docs-site/diagrams. Pinned end to end: Graphviz moves boxes between releases,
# and docs-diagrams-check compares bytes. Alpine for Graphviz 12: Debian's 2.42 crashes on
# orthogonal edges (maze.c chkSgraph).
FROM python:3.12-alpine3.24@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4

RUN apk add --no-cache graphviz=12.2.1-r3 font-dejavu=2.37-r6 fontconfig

# --no-deps: diagrams declares pre-commit, which drawing never imports.
COPY requirements.txt /tmp/diagram-requirements.txt
RUN pip install --no-cache-dir --no-deps --require-hashes \
    -r /tmp/diagram-requirements.txt
