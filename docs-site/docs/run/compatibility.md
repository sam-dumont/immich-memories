---
title: Immich version compatibility
---

# Immich version compatibility

The client implements **Immich v2 and v3 API contracts** and normally detects the major from
`/api/server/version`. That does not establish a minimum patch version or certify every release
in those series. Use `api_version: auto`; forcing `v2`/`v3` is a troubleshooting override, not a
way to make an unsupported server supported.

| Version or range | What is established | Evidence / recommendation |
|---|---|---|
| Immich 3.0, 3.1 and 3.2 families | Maintainer-tested release families | Exact patch versions and per-feature transcripts are not listed here for every historical run; these are not new RC acceptance results |
| Immich 2.7 and earlier releases | Maintainer-tested history | Earlier patch versions were not enumerated; this history does not establish a supported minimum |
| Immich v2.7.5 | Source-build CI pass with SQLite | [Real-Immich gate run](https://github.com/sam-dumont/immich-memories/actions/runs/37109268619), app source `d24e98d193287b341b5fa2d869095054483ffe1c`; prebuilt candidate evidence still required |
| Immich v3.2.2 | Source-build CI pass with SQLite | Same run and source commit; not a public candidate installation |
| Immich v3.2.2 with the published rehearsal wheel `0.0.0.dev37180797983` | Native arm64 Basic: preflight, a 39-asset album film (29.5 s) and a 248-asset month film (61 s) | Rehearsal `v0.0.0-dev.37180797983`, 2026-10-04; a pre-tag build, not a release acceptance |
| Other v2/v3 patch releases | API major implemented; exact patch compatibility not established here | Run `config test`, preflight and a bounded film; use the tested families above, then check exact candidate evidence in the matrix |
| Minimum supported patch | **Not established** | Do not infer a minimum from the oldest test target |
| Other major versions | Unsupported by the current automatic API policy | Use an implemented v2/v3 contract; a manual override does not validate another major |

No forthcoming-RC patch combination is marked tested on this page yet. Before installing for
that RC, consult [the deployment matrix](./tested-deployments.md) for actual app/Immich versions,
public inputs and completed film evidence. Historical measurements without an Immich patch
identity cannot fill this gap.

```bash
immich-memories config test
immich-memories preflight
```

In Docker prefix these with `docker compose exec immich-memories`. `config test` reports server
version and authenticated read access; it does not upload a film. Use the
[minimum read permissions](./docker.md#the-api-key) for a new key. Add upload/delete permissions
only for the separately enabled delivery features.
