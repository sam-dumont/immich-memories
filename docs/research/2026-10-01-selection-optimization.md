# Selection optimization measurements, 2026-10-01

Follow-up to #1692. Base: `b96d7d6a2`. Scope: cached editorial selection,
annotation storage and still preparation. Maps and video rendering belong to #1704.

## Real cached-month replay

The combined annotation parsing, privacy scanning, streaming thumbnail hash and
banked-head read changes reduced the M2 Pro median from **1.9406 s to 1.8114 s
(6.7%)**. Both variants already included the nearby-choice and compact-audit changes.

Eight fresh processes ran in ABBA order twice, with three measured iterations
per process: 12 observations per variant. Profiling ran separately from timing.
The replay used a frozen month of 1,072 assets and local copies of its caches.
All 24 runs produced the same 15 ordered selections, invoked zero cold producers,
and passed the replay guard. Ten factual tables plus thumbnail-hash and scene-print
cache fingerprints were unchanged. Metadata OCR responses were frozen from the
control, so network latency did not enter the timed comparison.

This is a cached selection result, not a fresh-library or complete-film speedup.
Long-lived exploratory runs showed timing drift; their medians are not used here.
Private source assets, identifiers, model paths and cache copies stay outside Git.

## Measured opportunities

| Change | Workload | M2 Pro result | Kubernetes CPU result |
|---|---|---|---|
| Nearby-choice indexing | Complete synthetic planner, 3,600 pictures | 346.7 to 316.7 ms | 6.5% and 6.9% lower medians on two nodes |
| Annotation parsing (#1725) | 10,000 reads of 1,000 lines | 15.7–16.6 to 3.5–3.7 ms | Exploratory 50–60 to 10–13 ms |
| Private-token scanning (#1726, #1731) | 2,000 lines, 2,200 tokens; includes matcher construction | 13.3 to 4.2 ms | Exploratory 48 to 9–11 ms |
| Current banked-head reads (#1724) | 1,000 assets, two heads, 20 historical versions | 54.9–55.5 to 8.1 ms | 179–203 to 24–33 ms |
| Streaming fingerprint (#1723) | 1,000 public preview payloads | 6.8–11.0% lower hashing time | Exploratory about 6% lower |

These isolated gains do not add up to an end-to-end percentage. Kubernetes timing
ranges overlap for the complete synthetic planner, so its modest median changes
need controlled confirmation. The database improvement depends on version history:
a current-only M2 fixture stayed around 8 ms with either implementation.

The original nearby-choice/compact-audit slice alone did not improve the real
month (1.958 to 1.984 s). Its scaling gain appears in the larger synthetic case.
The complete synthetic planner used 18 samples per variant per host; decisions
and prompts matched. A 1,000-group nearby-choice microbenchmark dropped from
384 to 1.4 ms on M2 and 1,366 to 5.8 ms on a Kubernetes CPU node.

## Why the changes preserve behavior

- Nearby alternatives are indexed by moment while retaining spacing, favourites,
  stable ties and time boundaries. Only private audit JSON loses indentation.
- A UnitLines reader remembers the current text and parsed description per asset.
  Text refreshes invalidate that entry. No process-global prose cache is added.
- Privacy scanning checks overlapping candidate prefixes in native regex code,
  then confirms complete literal tokens. Annotation and wall token policies stay
  separate. Unicode, punctuation and leak-refusal cases have regression tests.
- Thumbnail SHA-256 receives the same prefix and payload in separate updates.
  Persistent keys are identical, and changed preview bytes still invalidate them.
- Store queries select exact head/version pairs before hydration and fetch bounded
  partitions. SQLite bind limits and PostgreSQL reads were both exercised; the
  disposable PostgreSQL/SQLite annotation run passed 38 tests, with four skips.

## Preview reuse: measured, not shipped

Issue #1727 asked whether producers could share decoded still previews. The
existing producers traverse the whole pending cohort in separate passes. A small
LRU therefore evicts the first pass before the next producer reaches it.

The diagnostic uses five unique public JPEG fixtures repeated under 48 immutable
source indexes, three producer passes and three repeats. Capacity eight produces
**zero hits and 144 decodes**, exactly like no cache. Capacity 48 produces 96 hits
and 48 decodes, but retains **169,088,760 RGB bytes (161 MiB)**. This excludes input
payloads, model tensors, cache overhead and temporary decode allocations.

Run it with a directory containing public JPEG fixtures:

```sh
make benchmark-preview-reuse BENCHMARK_ARGS='--images /path/to/public-jpegs --assets 48 --capacity 8 --repeat 3'
```

The diagnostic compares dimensions and a sample pixel across traversals; that is
not a proof of complete producer parity. Five fixture decodes matched between
Pillow and OpenCV. Generated EXIF orientation 6 and 8 JPEGs did not: OpenCV
rotated the decoded pixels and changed thumbnail hashes, while the Pillow path
preserved stored orientation. Malformed input returned an empty thumbnail hash
but raised `UnidentifiedImageError` in pixel facts and DINO preprocessing.
Run `make benchmark-preview-contracts` to reproduce these contract differences.
A shared representation must preserve each existing producer recipe.

A useful bounded cache needs producer scheduling in common chunks or a shared
representation with explicit lifetime, identity and orientation rules. This PR
adds the reproducer instead of a zero-hit production cache. No speedup is claimed.

## Still producer costs and remaining limits

On M2, public-fixture decode alone averaged about 4.9 ms/picture; the Kubernetes
CPU run averaged 15.6 ms. Available M2 preparation stages totalled 78.3 ms/picture,
including 29.0 ms for DINO embeddings and 0.1 ms for banked heads. This excludes
unavailable detectors and the caption service.

The preparation harness had an obsolete Marqo PyTorch adapter. Issue #1732 fixes
it to call the shipped ONNX provider with an explicit local export path. Running
the corrected adapter on M2 measured 41.1 ms/picture across three measured cycles
of the five public JPEGs, after a 50.1 ms/picture cold pass. This was a separate
run, not a measurement of complete fresh-month preparation.

The remaining replay profile is mostly native hashing, file I/O, serialization
and video probes. The large checkpoint hash count comes from eight model files
in one identity check; it is not thousands of redundant model validations.
Skipping byte verification based only on filenames, asset IDs or stat data would
weaken replacement detection. Video metadata/probe work remains with #1704.

Reusing a CSV dialect saved less than 1 ms across 10,000 rows, below the measured
whole-month noise. A faster JSON dependency also changes non-finite-number
semantics. Neither justified another production patch. There is no demonstrated
Python numeric kernel here that warrants a Cython rewrite.

## Validation limits

Regression tests cover exact outputs, refresh invalidation, literal privacy
matching, persistent hash compatibility, query bind limits and bounded memory.
The real replay validates the combined changes; isolated timings identify where
they matter. These measurements do not replace fresh-library, full-film or
concurrent production-load benchmarks.
