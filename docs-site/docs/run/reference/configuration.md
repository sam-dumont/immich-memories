---
title: "Configuration sources and secrets"
---

# Configuration sources and secrets

## Where a setting comes from

Four sources, strongest first:

1. **Environment**: `IMMICH_MEMORIES_<SECTION>__<FIELD>` and the shortcuts in
   [environment variables](.././environment-variables.md) (`IMMICH_URL`, `IMMICH_API_KEY`, ...).
2. **`config.yaml`**: this file, which only you write.
3. **Database**: what the settings page, **Save Config** on the Settings page, and
   `immich-memories config --url URL --api-key KEY` saved. One row per key; a key you never saved has no
   row, so a new default still reaches you after an upgrade.
4. **Default**: the value in the [config reference](../../reference/config-reference.md).

If a store is configured (a PostgreSQL URL, or a SQLite file that exists) and its settings cannot
be read, the app does not start: the CLI exits with the error and the web UI refuses to start.
The message names the store (password masked) and the cause, such as a refused connection or a
corrupt file. Starting anyway on half the settings could send an automated run somewhere you did
not mean. Fix the database or its URL, or set `IMMICH_MEMORIES_SKIP_STORED_SETTINGS=1` to start on
env, `config.yaml` and defaults only. A SQLite store that does not exist yet is a fresh install and
starts silently.

The first source that sets a key wins, key by key: `advanced.llm.model` in the file and `llm.base_url`
in the database work together. The web UI greys out every setting the environment or the file sets
and names the variable or the file key; saving under it would do nothing.

`immich-memories config show` prints the same report: every key, its value, its source, and the
exact variable or file key that sets it. Secrets print as `***`. Give prefixes to narrow it:

```bash
immich-memories config show llm immich.url
```

### Moving a key out of the file

Nothing moves from `config.yaml` into the database on its own; an upgrade leaves your file in charge.
To hand a key to the UI:

```bash
immich-memories config move-to-db llm.model automation.cooldown_hours
```

Keys are runtime paths, without `advanced.`. Each value is saved to the database, then its line is
removed from the file, wherever it was written (top level or under `advanced:`). The rest of the file
keeps its values and its `${VAR}` references, but not its comments, so the previous file is kept
as `config.yaml.bak`. A key whose value is a `${VAR}` reference is refused: it already comes from
the environment. `database.url` and `database.schema` never move, because the app reads them before
the database opens.

### Secrets in the database

Keys named `api_key`, `caption_api_key`, `password`, `client_secret`, `trigger_token`,
`worker_token`, `token`, `secret`, `api_keys` or `urls` (notification URLs carry credentials) are
secrets. In the database they are encrypted with Fernet, under a key derived (HKDF-SHA256) from
`IMMICH_MEMORIES_SECRET_KEY`. Any string of at least 32 characters works; generate one with

```bash
openssl rand -base64 32
```

and keep it with your other secrets. Without it the UI and the CLI refuse to store a secret and say
so (Settings: "Secrets cannot be saved here until IMMICH_MEMORIES_SECRET_KEY is set"); put the
secret in the environment or `config.yaml` instead. It is read from the environment only. On
Docker the shipped compose file already passes it through, so set it in `.env`:

```bash
# .env
IMMICH_MEMORIES_SECRET_KEY=paste-the-openssl-output-here
```

Then `docker compose up -d` to recreate the container. A key shorter than 32 characters is refused
when you save. Change or lose the key and the
stored secrets stop opening: the app logs which ones and falls back to their defaults, `config show`
and the settings page mark each one, and you save them again. Logs never print a secret, whichever source it came from.


## Everyday keys and advanced keys

Everyday sections sit at the top level: `immich`, `defaults`, `output`, `audio`, `title_screens`,
`cache`, `database`, `upload`, `trips`, `network`, `photos`, `render`. Tuning sections
go under `advanced:`: `analysis`, `speech`, `hardware`, `llm`, `musicgen`, `ace_step`, `server`, `auth`, `automation`,
`notifications`, `triage`, `editorial`, `inference`, `free_text`. Both placements work and merge key by key at
every depth, and the top-level value wins a tie, so a hand-written
`editorial: {preparation: {caption_concurrency: 4}}` changes concurrency and keeps the rest of an
`advanced.editorial` block. The database, `config show` and `config move-to-db` use the runtime
path without `advanced.` (`llm.model`); the UI and `config show` name a file key the way you wrote
it (`advanced.llm.model`). The product tier controls preparation.

Unknown keys inside a section are ignored; unknown top-level keys and invalid values
(`codec: av1`) fail with a validation error. Check effective values with `config show` after editing.


## Paths in the config are host paths

Everything else in this file travels to another machine. These keys don't: they name paths on the
machine that wrote them. `immich-memories preflight` prints one `Config paths` warning naming every
path that is missing here, so a copied config fails up front instead of hours into a run.

| Key | What it points at |
|---|---|
| `output.directory` | where finished films are written |
| `cache.directory` | previews, thumbnails, downloaded clips |
| `cache.database` | its directory holds run lock files; operational facts and history live in the store |
| `database.url` | the store (banked facts and readings, your picture decisions and review edits, people, settings, run history, automation state, special days), when it is a SQLite file (`sqlite:///~/.immich-memories/store.db`) |
| `advanced.editorial.annotation_database` | its parent directory holds `structure-banks/` thumbnail-hash and scene-print caches; facts live in the store |
| `advanced.triage.encoder` | the pinned DINOv2 ONNX export |
| `advanced.editorial.preparation.head_bundle` | a head bundle of your own, for the eight context heads |
| `advanced.editorial.preparation.marqo_onnx` | the pinned sensitive-content export |
| `advanced.editorial.preparation.detector_cache_dir` | the Hugging Face cache the detectors read |
| `advanced.editorial.preparation.detector_python` | an interpreter for the detector worker |
| `audio.local_music_dir` | your own music, read by `immich-memories music` |

Blank is the default for `head_bundle`, `detector_python` and `detector_cache_dir`, and the portable
value: it means "work it out here". A `detector_python` that is not on this host (a Mac venv
path carried into a NAS container, or a venv deleted since) stops a cut before it reads a picture,
naming the key; `immich-memories preflight` shows the same row. Remove the key and the detectors run on the app's own
Python. Containers already pin most of these: the image sets
`output.directory` to `/app/output`, and the [Kubernetes manifests](.././kubernetes.md) put the model
paths on the `/models` claim.


## Environment variable substitution

These fields expand `${VAR_NAME}` at load time:

| Section | Fields |
|---|---|
| `immich` | `url`, `api_key` |
| `llm` | `api_key` |
| `musicgen` | `base_url`, `api_key` |
| `ace_step` | `api_url`, `api_key` |
| `auth` | `password`, `client_secret`, `issuer_url`, `client_id` |
| `render` | `worker_base_url`, `worker_token` |
| `editorial` | `annotation_database` |
| `editorial.preparation` | `head_bundle`, `detector_python`, `detector_cache_dir`, `marqo_onnx`, `caption_api_key` |

Only the braced form expands. A bare `$VAR` stays as written, because a `$` in a password is
ordinary (a warning says so if it matches a variable you have set). For any other field, use
`IMMICH_MEMORIES_<SECTION>__<FIELD>` ([environment variables](.././environment-variables.md)).

## Immich API compatibility

```yaml
immich:
  api_version: auto # auto | v2 | v3
```

Immich v2 and v3 both work. `auto` is the default runtime policy: the app detects the server
major and selects the matching API contract. You do not choose a version for each run. Explicit
`v2` and `v3` values are manual troubleshooting escape hatches for proxies or unusual deployments
that break version detection. An override forces that contract; it is not a normal upgrade step.
Durations, upload fields and search dates are converted for each version, and an unknown major
stops the run with `UnsupportedImmichVersion` rather than sending requests of the wrong shape.

```bash
immich-memories config test
```

Read-only: it reports the connection and the resolved contract, and does nothing else.

### API wire details

Explicit `v2` and `v3` are manual troubleshooting escape hatches for unusual proxies
or deployments that prevent correct detection; they force the selected contract.

- **Duration:** v2 duration strings and v3 integer milliseconds are normalized to seconds.
- **Upload:** v2 keeps the device identity fields; v3 sends `filename` and omits the
  removed `deviceAssetId` and `deviceId` fields.
- **Search dates:** date bounds include a UTC offset, which v3 requires.

```bash
immich-memories config test
```

This is a read-only authentication and compatibility check. It does not search assets,
generate a video, create an album, or upload anything.

## Output codecs and HDR

`codec: h265` with `hdr_mode: auto` can retain HDR when supported by the selected output path.
H.264 is always SDR and tone-maps HDR sources. NAS output remains capped at 1080p.
