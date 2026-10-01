---
title: Benchmarking and release films
---

# Benchmarking and release films

Compare routes with fixed material and settings. Keep fresh and warm caches separate, record the commit and hardware, and retain failures as failures. Elapsed time, reported token cost and the film you prefer are separate results.

## Rendering one of each memory type

A different driver, for a different question. When selection changes, one film tells you almost
nothing: you need one of each kind (a month, a person, a trip, a year, an album) rendered the same
way, uploaded to the same place, watched back to back. `scripts/matrix_routes.py` drives that through
the public CLI and adds no selection logic of its own.

`examples/matrix-routes.example.json` lists eleven routes, each naming a memory type, a target
duration, a bundled music loop and a scope whose values are `@placeholders`. Which year, which person,
which album never enter the repository: they live in an overlay file of your own, outside it, which
also carries the output root, the album name and an optional `reference` block holding the plan hash
of a run you already approved. A placeholder with no value is a hard error at `build` time, never a
skip, because rendering nine routes and quietly dropping the tenth is how you end up grading a matrix
with a hole in it.

```bash
python scripts/matrix_routes.py build   --routes examples/matrix-routes.example.json \
                                        --private ~/matrix/private.json \
                                        --manifest ~/matrix/manifest.private.json
python scripts/matrix_routes.py run     --manifest ~/matrix/manifest.private.json
python scripts/matrix_routes.py collect --manifest ~/matrix/manifest.private.json
python scripts/matrix_routes.py report  --manifest ~/matrix/manifest.private.json
```

`build` checks every flag it produces against the live Click tree, so a renamed option fails here
rather than three hours into a batch, and it gives every case the same fixed flags so the route is
the only thing that varies. `run` is serial and resumable, holds an exclusive lock on the manifest,
re-checks the frozen config's SHA-256 before every case and refuses to start below a 50 GiB free-disk
floor. `collect` never trusts an exit code: one `.mp4` per case at 1920x1080, an audio stream, the
`Audio mixed successfully` line, and a full `ffmpeg -xerror … -f null -` decode of both streams, and
if the batch asked for an upload and no Immich asset id was recorded the case is `failed` rather than
`ready`.

`report` is the part that decides anything:

| Verdict | Means |
|---|---|
| `identical` | The plan bytes match the accepted run. Your previous grade stands |
| `same-carriers` | Different plan, same clips in the same order. Something around selection moved; the cut did not |
| `changed; owner approval not transferred` | A different cut. Watch it |
| `no reference` | Nothing banked for this route yet |
| `not collected` | `collect` has not run, or it failed |

One dated album per matrix, named in the overlay, so the whole set is one scroll in Immich and old
batches never mix into a new one. The eleventh route, `monthly-supersede`, exists to exercise one
behaviour: uploading a memory whose recipe already exists in the album should trash the older copy
rather than sit beside it. After the batch that album should hold ten films, not eleven.

<span id="the-reader-bake-off"></span>
<span id="four-rules-that-make-the-numbers-mean-anything"></span>
<span id="cost-is-the-price-list-times-the-tokens"></span>
<span id="running-it"></span>
<span id="what-lands-in-the-output"></span>
