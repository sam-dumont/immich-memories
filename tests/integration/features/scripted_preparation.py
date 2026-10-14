"""A Basic preparation whose model producers answer from the fixture library, not from ONNX.

`real_editor.py` prepares at `metadata_only`, which runs no detector at all, so nothing a
detector head banks (the people head, the exposure heads, a clip's frame reading) ever reaches
a hermetic film. Here the child keeps Basic's own `no_captions` preparation, the one a user's
`generate` runs, and swaps only the producers that need the pinned DINOv2, Marqo and Docling
exports for scripted ones (`PreparationPorts`, the seam the preparation keeps for this):

- each producer is asked for exactly the sources and heads the real preparation demands, and
  banks one row per (source, head) in the store's `head_facts`, as the real producer does;
- the answer is what the fixture picture shows: the people head counts the faces Immich holds
  on it, a Live Photo's clip shows what its still shows, and every exposure head reads clean.

Everything around them is production: which sources owe which head, the reads that correct a
head against Immich's faces, the editor, the cut and the render. A producer can be told to read
something else on given ids (``SCRIPTED_HEADS``), the way a real head errs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from tests.features.cli_harness import CliResult, UserHome
from tests.integration.features import real_editor

# Child env: JSON {asset id: {head: label}} a scripted producer answers instead of the picture.
SCRIPTED_HEADS = "FEATURE_SCRIPTED_HEADS"
# Child env: where the child writes, per producer, the ids it was asked to read (JSON lines).
PRODUCER_LOG = "FEATURE_PRODUCER_LOG"

_SCRIPTED_PREPARATION = """
import json
import os
import sys
from functools import partial

import immich_memories.analysis.editorial_preparation as editorial_preparation
import immich_memories.analysis.place_geocoder as place_geocoder

from tests.e2e.fake_editorial import _stand_in_for_models_fetch
from tests.integration.features.scripted_producers import scripted_ports

# WHY: preflight refuses a Basic film without the pinned exports; the producers that would read
# them are the scripted ones below, so only the install check has to see them.
_stand_in_for_models_fetch()

# WHY: the model producers run on pinned ONNX exports `models fetch` downloads; a hermetic run
# has none. Every other stage of Basic's no_captions preparation stays production code.
editorial_preparation.PreparationPorts = partial(
    editorial_preparation.PreparationPorts,
    **scripted_ports(
        json.loads(os.environ.get("FEATURE_SCRIPTED_HEADS") or "{}"),
        os.environ.get("FEATURE_PRODUCER_LOG") or None,
    ),
)
# WHY: the fixture places are public and named by the fake Immich; nothing asks the internet.
place_geocoder.nominatim_fetch = lambda *_args, **_kwargs: lambda *_point: None

from immich_memories.cli import main

sys.argv = ["immich-memories", *sys.argv[1:]]
main()
"""


def run_prepared(
    home: UserHome,
    *args: str,
    heads: Mapping[str, Mapping[str, str]] | None = None,
    log: str | None = None,
) -> CliResult:
    """`immich-memories <args>` with the real editor and the scripted model producers."""
    env = {SCRIPTED_HEADS: json.dumps(heads or {})}
    if log:
        env[PRODUCER_LOG] = log
    return real_editor.run(home, *args, child=_SCRIPTED_PREPARATION, env=env)
