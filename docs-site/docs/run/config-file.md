---
sidebar_position: 1
title: Config File
---

# Config file

`~/.immich-memories/config.yaml` is yours: the app reads it and never writes it, except when you
run `immich-memories config move-to-db`. Keep it at permissions `600` if it holds API keys. What
you save from the web UI or `immich-memories config` goes to the database instead (see
[where a setting comes from](#where-a-setting-comes-from)). The annotated example is
[`examples/config.example.yaml`](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/examples/config.example.yaml),
and every key with its default is in the [config reference](../reference/config-reference.md). In
Docker you can skip the file entirely and use [environment variables](./environment-variables.md).

## Where a setting comes from

Four sources, strongest first:

```mermaid
flowchart LR
    E["Environment<br/>IMMICH_MEMORIES_LLM__MODEL"] --> F["config.yaml<br/>advanced.llm.model"]
    F --> D["Database<br/>saved from the UI or CLI"]
    D --> X["Default"]
```

1. **Environment**: `IMMICH_MEMORIES_<SECTION>__<FIELD>` and the shortcuts in
   [environment variables](./environment-variables.md) (`IMMICH_URL`, `IMMICH_API_KEY`, ...).
2. **`config.yaml`**: this file, which only you write.
3. **Database**: what the settings page, **Save Config** on the Memory page, and
   `immich-memories config --url/--api-key` saved. One row per key; a key you never saved has no
   row, so a new default still reaches you after an upgrade.
4. **Default**: the value in the [config reference](../reference/config-reference.md).

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
so; put the secret in the environment or `config.yaml` instead. Change or lose the key and the
stored secrets stop opening: the app logs which ones and falls back to their defaults, `config show`
and the settings page mark each one, and you save them again. Logs never print a secret, whichever source it came from.

## Compute tier

Leave `tier` unset, or set `tier: auto`: the app picks `nas`, `gpu` or `full` from what it finds.
How it decides: [The three tiers](./requirements.md#the-preparation-tier). Captions from a
vision-capable LLM instead of the caption server are a separate, explicit switch:
[LLM captions](../better/captions.md#explicit-llm-captions).

## Quick start config

A full plain-NAS setup, every default kept except the two values that make a cut good
(where home is, and where films go).

```yaml
immich:
  url: "https://photos.example.com"
  api_key: "${IMMICH_API_KEY}"
  api_version: auto  # auto | v2 | v3

trips:
  homebase_latitude: 50.85      # without these, no trip is ever a trip
  homebase_longitude: 4.35

output:
  directory: "~/Videos/Memories"
  resolution: "1080p"            # 720p, 1080p, 4k
  codec: h264                     # the default; h265 keeps HDR
  hdr_mode: auto                  # keep HLG/PQ when present, otherwise SDR
```

Everything else has a default. With `codec: h265` and `hdr_mode: auto`, HLG or PQ footage gives a
10-bit HDR film and SDR clips, photos and titles are converted to the same transfer. H.264 is
always SDR and tone-maps HDR sources.

Trip detection needs both home coordinates. Preflight warns when either is missing or left at
`(0, 0)`, and trips stay off until you set them.

### Make it better (optional)

A reader is one block. Leave it out and the app edits on a plain NAS, which is the default and the
tier most installs run; a model makes the cut better. What a model adds and costs is on [the overview](../better/overview.md).

```yaml
llm:
  provider: "openai-compatible"
  base_url: "http://localhost:8000/v1"
  model: "gemma-4-e4b-it-6bit"
```

## Everyday keys and advanced keys

Everyday sections sit at the top level: `immich`, `defaults`, `output`, `audio`, `title_screens`,
`cache`, `database`, `upload`, `trips`, `network`, `photos`, `render`, `title_llm`. Tuning sections
go under `advanced:`: `analysis`, `speech`, `hardware`, `llm`, `musicgen`, `ace_step`, `server`, `auth`, `automation`,
`notifications`, `triage`, `editorial`, `inference`. Both placements work and merge key by key at
every depth, and the top-level value wins a tie, so a hand-written
`editorial: {preparation: {caption_concurrency: 4}}` changes concurrency and keeps the rest of an
`advanced.editorial` block. The database, `config show` and `config move-to-db` use the runtime
path without `advanced.` (`llm.model`); the UI and `config show` name a file key the way you wrote
it (`advanced.llm.model`). Preparation's former tier override no longer takes precedence
over the product tier.

Unknown keys inside a section are ignored. The keys of the retired per-clip scorer
(`content_analysis`, `audio_content`, `transcription`, `description_llm`,
`analysis.max_refinement_passes`, `photos.max_ratio` and their family), the retired `scheduler:`
section and a few dials nothing read (`cache.max_age_days`, `title_screens.show_decorative_lines`,
`triage.enabled`, `triage.bundle`) are dropped by name with a warning, so an old file loads and
tells you what it ignored. Unknown top-level keys and invalid
values (`codec: av1`) fail with a validation error.

## Paths in the config are host paths

Everything else in this file travels to another machine. These keys don't: they name paths on the
machine that wrote them. `immich-memories preflight` prints one `Config paths` warning naming every
path that is missing here, so a copied config fails up front instead of hours into a run.

| Key | What it points at |
|---|---|
| `output.directory` | where finished films are written |
| `cache.directory` | previews, thumbnails, downloaded clips |
| `cache.database` | derived analysis (safe to lose; it is rebuilt) |
| `database.url` | the store (banked facts and readings, your picture decisions and review edits, people, settings, run history, automation state, special days), when it is a SQLite file (`sqlite:///~/.immich-memories/store.db`) |
| `advanced.editorial.annotation_database` | deprecated: a legacy `annotations.sqlite` the store imports once; its directory still holds `structure-banks/` (the thumbnail-hash and scene-print caches, and any legacy JSON banks the store imports) |
| `advanced.triage.encoder` | the pinned DINOv2 ONNX export |
| `advanced.editorial.preparation.head_bundle` | a head bundle of your own, for the eight context heads |
| `advanced.editorial.preparation.marqo_onnx` | the pinned sensitive-content export |
| `advanced.editorial.preparation.detector_cache_dir` | the Hugging Face cache the detectors read |
| `advanced.editorial.preparation.detector_python` | an interpreter for the detector worker |
| `audio.local_music_dir` | your own music, read by `immich-memories music` |

Blank is the default for `head_bundle`, `detector_python` and `detector_cache_dir`, and the portable
value: it means "work it out here". A `detector_python` that is not on this host (a Mac venv
path carried into a NAS container, or a venv deleted since) stops a cut before it reads a picture,
naming the key; `doctor` shows the same row. Remove the key and the detectors run on the app's own
Python. Containers already pin most of these: the image sets
`output.directory` to `/app/output`, and the [Kubernetes manifests](./kubernetes.md) put the model
paths on the `/models` claim.

## Footage the camera roll did not shoot

Doorbells, screen recorders and messaging apps upload into the same timeline as your phone. Files
matching these patterns never reach selection:

```yaml
advanced:
  analysis:
    exclude_filename_patterns:
      - "RingVideo_*"
      - "RPReplay_Final*"
      - "Screen Recording *"
      - "Screenshot*"
      - "img-*-wa[0-9][0-9][0-9][0-9]*"
      - "vid-*-wa[0-9][0-9][0-9][0-9]*"
```

Case-insensitive globs on the original filename. Setting the key replaces the list, so copy the
defaults you want to keep.

A still whose EXIF names no camera is dropped too (`exclude_stills_without_camera_exif: true`, the
default): on iOS a photo saved from a messaging app keeps its `IMG_` name and loses only the camera
make. Turn it off if your library is mostly exported or edited originals, which lose the make the
same way. Videos are exempt.

## Immich API compatibility

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

## Environment variable substitution

These fields expand `${VAR_NAME}` at load time:

| Section | Fields |
|---|---|
| `immich` | `url`, `api_key` |
| `llm` / `title_llm` | `api_key` |
| `musicgen` | `base_url`, `api_key` |
| `ace_step` | `api_url`, `api_key` |
| `auth` | `password`, `client_secret`, `issuer_url`, `client_id` |
| `render` | `worker_base_url`, `worker_token` |
| `editorial` | `annotation_database` |
| `editorial.preparation` | `head_bundle`, `detector_python`, `detector_cache_dir`, `marqo_onnx`, `caption_api_key` |

Only the braced form expands. A bare `$VAR` stays as written, because a `$` in a password is
ordinary (a warning says so if it matches a variable you have set). For any other field, use
`IMMICH_MEMORIES_<SECTION>__<FIELD>` ([environment variables](./environment-variables.md)).

## Upload back to Immich

```yaml
upload:
  enabled: true
  album_name: "2024 Memories"
```

Off by default. [What Immich sees](./privacy.md#what-immich-sees) lists every write it makes.

## Outside calls

```yaml
network:
  geocoding: false        # nominatim.openstreetmap.org
  geocoding_url: ""       # your own Nominatim instead, e.g. http://nominatim.lan:8080
  map_tiles: false        # server.arcgisonline.com
```

Both off, so a default run reaches your Immich server, the endpoints named elsewhere in this file,
and nothing else. `geocoding` buys the right district's name where Immich names the neighbouring
town (Wilrijk, not Hoboken), trip names from the map, and place names in the film's language. It
sends rounded coordinates, about a kilometre, once per place; answers are kept in the store.
`geocoding_url` points it at a self-hosted Nominatim. `map_tiles` buys the trip fly-over and the
map behind location cards. Fonts are never fetched at run time (see
[fonts](./privacy.md#fonts)). [Privacy](./privacy.md) says exactly what each host receives.

## Reader concurrency

Only matters with a reader. `advanced.llm.reader_concurrency` is unset by default and then read
from `llm.base_url`: 1 for a loopback or private address or a bare service name, 4 for a public
host. A model on your own machine is one process in front of one accelerator, so four requests
queue there instead of overlapping; a hosted endpoint is a fleet. Set it yourself (1 to 16) for a
local server that does take concurrent requests, or a provider that wants a lower rate.
