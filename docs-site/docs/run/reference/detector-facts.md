---
title: Detector facts and refreshes
---

# Detector facts and refreshes

For inspecting prepared model answers, changing custom weights, or refreshing a known bad answer.
Normal upgrades do not require this. Back up the [store](../database.md#managing-the-store) before changing it.

## Detector cache contract for 1.0.0

`detector-facts-v1` freezes the banked detector format. A fact keeps its asset ID, head name,
producer version, label, confidence, encoder identity and decision time. The lookup key remains
`(asset_id, head, version)`. The application version is not part of that key: installing 1.0.0 or
upgrading a container does not, by itself, make a prepared library cold again.

The frozen producer versions are:

| Producer | Version |
|---|---|
| DINO activity, children, location, people, frame kind and uncovered person | `public-v1` |
| DINO venue | `oi-v3` |
| DINO screen | `public-v1-strict` |
| Marqo exposure | `det-v3` |
| Docling document type | `det-v2` |
| Sampled video frame kind | `frame_kind-public-v1/8-frames` |

The v1 fixture also pins model/export digests, the head bundle, label sets, the preprocessing
identity and video sampling. A producer that changes those semantics needs a new producer version
and an explicit compatibility decision. Existing answers keep their original version.

### Inspect and migrate

```bash
immich-memories store facts status
immich-memories store facts status --json
immich-memories store facts migrate          # preview only; no inference
immich-memories store facts migrate --apply  # copy proven compatible answers
```

`status` groups existing facts by producer, version and compatibility. `reusable` means the row
matches the configured producer and has a valid label/confidence. `superseded` means a current row
already exists beside an older one. `migrate` means an answer can carry forward without inference.
`refresh` means the old or malformed answer does not satisfy the current producer. `unrecognized`
means that head is outside the configured set; it is preserved. This reports stored facts, not
missing assets across an entire library. `prepare` reports missing coverage for a chosen scope.

The compatible migration in v1 copies Marqo `det-v2` still-photo answers to `det-v3`, only when
stored metadata confirms a photo and the encoder identity matches. The newer contract changed
video sampling, not still inference. Videos, Live Photo clips, unknown media kinds and answers
from a different encoder cannot use that migration. Preparation already carries qualifying stills
forward as it reaches them; this command lets you do it ahead of time.

Migration retains the old row, timestamp, label and confidence, and never overwrites an existing
newer answer. Repeating it is safe. Its report names the producer, count and up to 20 asset IDs.
It changes no media, captions or owner decisions. Run `store backup` before maintenance if you
want a rollback point. Database schema upgrades and legacy-file imports remain separate from
this detector migration.

### When a refresh is needed

| Change | Detector work |
|---|---|
| App version, image rebuild, CPU/GPU host, inference URL or concurrency | Reuse facts with the same producer contract |
| Selection tier, film duration, output resolution or music | Reuse compatible facts; prepare only newly required producers |
| New asset | Prepare that asset once |
| Changed weights, preprocessing, labels, confidence meaning or frame sampling | New producer version; migrate only proven equivalents, otherwise prepare affected facts |
| Source pixels replaced under the same asset ID, or a known bad cached answer | Explicitly refresh the affected asset/head pairs |

V1 detector lookups do not compare source-file checksums on every cut. Replacing source pixels
under the same Immich asset ID therefore needs an explicit refresh; changing a filename or date
alone does not require new pixel inference. Custom head bundles must use new head versions when
their meaning changes. Reusing an old version for different weights breaks the cache contract.

Stop preparation workers before an explicit refresh, then preview the exact scope:

```bash
immich-memories store facts refresh --head nsfw_marqo --asset ASSET_ID
immich-memories store facts refresh --head nsfw_marqo --asset ASSET_ID --apply
immich-memories prepare --year 2024 --month 6
```

Repeat `--head` or `--asset` for more than one. Both are required. `--apply` removes all versions
of only those head/asset pairs, so an older equivalent answer cannot immediately migrate back.
Other detector facts, captions, pixel measurements and owner decisions stay banked. This command
runs no model; the next `prepare` or cut recomputes the missing required facts and banks them as
usual. An interrupted preparation resumes the remaining work. For a changed producer version,
ordinary `prepare` already finds what is missing; you do not need to delete the old version first.

Keep the store volume, as well as downloaded model weights, across container upgrades. Deleting
`store.db` discards these banked answers. Use `store copy` to move them between SQLite and PostgreSQL.
