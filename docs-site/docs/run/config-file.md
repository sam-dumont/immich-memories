---
title: Configuration
---

# Configuration

Change a setting in **Settings** for the easy route. Use a file or environment variables when you
want the deployment to control it. Settings saves to the database; the app normally only reads
`~/.immich-memories/config.yaml`.

## Quick start config

```yaml
immich:
  url: "https://photos.example.com"
  api_key: "${IMMICH_API_KEY}"

trips:
  homebase_latitude: 50.85
  homebase_longitude: 4.35

output:
  directory: "~/Videos/Memories"
```

Both home coordinates are needed for trips. Everything else keeps its default.
Every server URL (`immich.url`, `llm.base_url`, `network.geocoding_url` and the rest) must start
with `http://` or `https://`; anything else is refused when the file loads or a setting is saved.
Keep the file at permissions `600` if it contains credentials.
Docker can use [environment variables](./environment-variables.md) without a file.

## Where a setting comes from

For each key, the first source that sets it wins:

| Priority | Source |
|---|---|
| 1 | Environment variables |
| 2 | `config.yaml` |
| 3 | Values saved from Settings or the config CLI |
| 4 | Built-in defaults |

Command-specific flags can override these for that command. LLM key shorthands have a
[special rule](./environment-variables.md#shorthands).
The UI greys out settings controlled by the file or environment and shows their source.

Some keys never come from Settings. Authentication (`auth.*`) and server (`server.*`) settings,
like the database location, are set in the environment or `config.yaml` and take effect on
restart. Settings shows them read-only. A value for one of them saved by an older version is
ignored at startup, and `preflight` names it.

A new URL for a server that receives a credential (Immich, an extra account, the LLM, the caption
server, MusicGen, ACE-Step) needs that credential typed again in the same save, when one is set.
A new render worker URL always needs its token, since the worker receives your Immich keys.

### Keys pinned by Docker

The shipped Compose file and image always set these, so YAML and Settings cannot override them:

| Runtime key | Docker value |
|---|---|
| `immich.url` | `IMMICH_URL`, default `http://immich-server:2283` |
| `tier` | `auto` |
| `trips.homebase_latitude`, `trips.homebase_longitude` | The corresponding `.env` variables, default `0` (home unset) |
| `editorial.preparation.detector_cache_dir` | `/home/immich/.immich-memories/models/huggingface` |
| `output.directory` | `/app/output` (image default) |

`IMMICH_API_KEY` also pins `immich.api_key` when nonempty. The auth pair takes effect when both
values are nonempty. Uncommented optional environment lines pin their keys too.
Change values in Compose or `.env`, then run `docker compose up -d`.
To let Settings control a Compose-pinned key, remove its environment line and any YAML value.
Keep the model cache and output paths on mounted volumes.

Inspect the same result from the CLI:

```bash
immich-memories config show llm immich.url
```

Secrets print as `***`. `--config PATH` selects one file for the CLI, UI, authentication and reloads.
If a configured store is unreadable, startup stops rather than silently using different settings.
Fix the database, or use `IMMICH_MEMORIES_SKIP_STORED_SETTINGS=1` for a deliberate recovery start
without its saved settings.

### Moving a key out of the file

To let Settings control a key currently in YAML:

```bash
immich-memories config move-to-db llm.model automation.cooldown_hours
```

Use runtime paths without `advanced.`. The command saves each value, removes its YAML entry and
keeps a `config.yaml.bak` (the rewrite loses comments). `${VAR}` values and database URL/schema
cannot move. An upgrade does not move keys automatically.

### Secrets in the database

Saving credentials from Settings or the CLI needs `IMMICH_MEMORIES_SECRET_KEY`:

```bash
openssl rand -base64 32
```

Keep the output with your other secrets. On Docker, put it in `.env` and recreate:

```ini
IMMICH_MEMORIES_SECRET_KEY=paste-the-generated-value-here
```

```bash
docker compose up -d
```

The key must be at least 32 characters. Without it, keep credentials in environment variables or
YAML; secret saves are refused. Losing it means re-entering saved credentials.
This is separate from the UI's [session signing key](./authentication.mdx#sessions).

## What each top-level section is for

| Want to change | Section | Guide |
|---|---|---|
| Immich connection or extra accounts | `immich` | [Accounts](./multi-account.mdx) |
| Home base and trip detection | `trips` | [Memory types](../make/memory-types.mdx#trip) |
| Sharing, transitions and captions | `defaults` | [Sharing](../reference/selection-internals/family-audience-duplicates.md#sharing-levels) |
| Resolution, codec and HDR | `output` | [Photos and HDR](../make/photos-and-live-photos.md) |
| Photo timing | `photos` | [Photos](../make/photos-and-live-photos.md) |
| Titles, maps and music | `title_screens`, `audio` | [Titles, maps and music](../make/titles-maps-music.md) |
| Upload destination | `upload` | [What Immich sees](./privacy.md#what-immich-sees) |
| Place names and map tiles | `network` | [Outside calls](./privacy.md#geocoding-and-maps) |
| Disk usage and persistence | `cache`, `database` | [Caches](./maintenance/health-logs-cache.md#caches), [database](./database.md) |
| A model or service | `advanced.llm`, `advanced.inference`, `render` | [Add-ons](../get-started/what-a-gpu-or-a-model-adds.md) |
| Login or daily schedule | `advanced.auth`, `advanced.automation` | [Authentication](./authentication.mdx), [automation](../make/automate.md) |

Every key/default is in the [config reference](../reference/config-reference.md).
The [annotated example](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/examples/config.example.yaml)
is there when you need a larger file.

## Everyday keys and advanced keys

Everyday settings live at the top level. Tuning sections live under `advanced:`:

```yaml
advanced:
  llm:
    provider: openai-compatible
    base_url: "http://localhost:8000/v1"
    model: "your-model-name"
```

Both placements are accepted and merge key by key; a top-level key wins a tie.
Environment variables and CLI paths always omit `advanced.` (`llm.model`). Unknown fields inside
a section still load, but each ignored key produces a warning naming the key, without its value.
Unknown `IMMICH_MEMORIES_*` variables are reported too; recognized process controls and aliases
are accepted. `preflight` and `config show` list ignored keys. Unknown top-level sections or invalid
values still fail validation.
Use `config show` to check effective values after editing.

## Paths in the config are host paths

Paths refer to the machine **running the app**. Inside Docker, `output.directory` must be a
container path, not a desktop folder. The image already sets `/app/output`; mount your host folder
there. Environment variables override file paths.

`preflight` flags missing paths. Remove an old `advanced.editorial.preparation.detector_python`
when moving a config between machines: blank uses the app's Python.
[The reference](../reference/config-reference.md) lists model/cache path overrides.

## Environment variable substitution

Use `${VAR_NAME}`, not `$VAR`. Substitution happens only in `config.yaml`, for [credentials and
selected service/path fields](./reference/configuration.md#environment-variable-substitution); it is not applied to every string. Settings and environment
variables are always taken as written: a Settings value containing `${` is refused there and by
the config CLI, and a saved value holding one (from an older version) is ignored at startup, with
`preflight` naming its key. For any config key, the reliable alternative is its
[`IMMICH_MEMORIES_SECTION__FIELD` variable](./environment-variables.md#the-pattern).

## Compute tier

Leave `tier: auto`. [Requirements and tiers](./requirements.md#the-preparation-tier) explains the
choice and required services.

## Immich API compatibility

Leave `immich.api_version: auto`; v2 and v3 are detected. `v2`/`v3` overrides are for diagnosing
unusual proxies, not a normal upgrade step. An unknown major stops the run.

```bash
immich-memories config test
```

This only checks authentication/API compatibility. It does not generate or upload.

## A second Immich account

Follow [A second account](./multi-account.mdx) to connect a partner's library, bind matching people
and select both accounts. The primary remains the only upload target.

## Footage the camera roll did not shoot

Filename patterns and the camera-EXIF filter exclude doorbell recordings, screenshots and saved
messaging-app images. [Selection boundaries](../how-it-chooses/family-audience-duplicates.md)
and the [analysis config reference](../reference/config-reference.md) explain how to adjust them.

## Upload back to Immich

```yaml
upload:
  enabled: true
  album_name: "Memories"
```

Off by default. The web Render panel has its own upload choice.
[Privacy](./privacy.md#what-immich-sees) lists every write.

## Outside calls

Geocoding and map tiles are off by default. Enable them under `network` only after reading
[what leaves your network](./privacy.md).

## Reader configuration changes before 1.0

A model name or endpoint no longer enables the reader implicitly. Add
`advanced.llm.enabled: true` to retain LLM calls. With it off, preflight warns when a reader is
configured but disabled.

The separate title-model configuration has been removed without a compatibility fallback.
Remove that old section and move its endpoint, model and credentials to `advanced.llm`.
This one section now serves titles, the selection reader, music mood, special days and explicit
LLM captions. Choose which former model should handle all those calls before upgrading.

If startup reports `title_llm is removed`, first remove that block from YAML. If the old
section was also saved in Settings, run this with the same Python environment and database
environment variables as the app. It deletes only the old section's saved keys and keeps
existing `llm` settings. For a custom config, replace `Config.get_default_path()` with
`Path("/path/to/config.yaml")`.

For Docker, replace the first line below with `docker compose run --rm -T immich-memories python - <<'PYTHON'`; use the same script and closing marker.

```bash
python - <<'PYTHON'
from pathlib import Path
from immich_memories.config import Config
from immich_memories.settings_store import settings_store

path = Config.get_default_path()
config = Config.from_yaml(path, stored={})
store = settings_store(config, create=False)
if store is not None:
    store.delete(
        key for key in store.stored_keys()
        if key == "title_llm" or key.startswith("title_llm.")
    )
PYTHON
```

## Reader concurrency

Use `advanced.llm.reader_concurrency` only when tuning model throughput. The default is one
request for loopback, a private IP or a bare service name, and four for a dotted DNS name or
public IP. A dotted LAN name still counts as hosted. Accepted overrides for external servers:
1–16; the owned reader always runs one request at a time.
See [Reader setup](../better/reader.md).


## Invalid configuration

A YAML configuration must be a mapping of setting names to values. An empty file or `null`
means no file overrides; scalar values and lists are rejected. Unknown authentication keys
are errors, so a misspelled `enabled` cannot silently leave authentication off.
Configured service URLs also follow the [address policy](./network-security.md#configured-service-addresses).

## Product tier names

The product tiers are `basic`, `gpu` and `full`. Basic uses CPU classifiers and rules; it is
not restricted to NAS hardware. `auto` chooses from available inference capability. Existing
`nas` values in YAML, environment variables and saved Settings still load as Basic. Config
and capability output use the canonical value `basic`.
