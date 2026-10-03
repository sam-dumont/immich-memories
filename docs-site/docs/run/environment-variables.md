---
title: Environment variables
---

# Environment variables

Environment variables override YAML and Settings. Use them to keep a deployment's settings fixed.
The UI shows which variable controls a setting.

## `.env` and `example.env`

Docker Compose reads `.env` for **substitution in the Compose file**. It does not pass every line
to the container. The service's `environment:` block must name the variable.
All variables in the shipped `example.env` are already wired up.

```ini
IMMICH_URL=http://192.168.1.10:2283
IMMICH_API_KEY=your-api-key
TZ=Europe/Brussels
```

Home coordinates are not in the shipped `.env` contract. Set them in Settings, or add them
to the app's `environment:` block in `docker-compose.yml`:

```yaml
      IMMICH_MEMORIES_TRIPS__HOMEBASE_LATITUDE: "50.8503"
      IMMICH_MEMORIES_TRIPS__HOMEBASE_LONGITUDE: "4.3517"
```

After an edit:

```bash
docker compose up -d
```

`restart` does not reload environment variables. For another setting, add it to `environment:`:

```yaml
      IMMICH_MEMORIES_UPLOAD__ENABLED: "true"
```

## The variables you are most likely to set

| Variable | Purpose |
|---|---|
| `IMMICH_URL`, `IMMICH_API_KEY` | Required Immich connection |
| `IMMICH_MEMORIES_TRIPS__HOMEBASE_LATITUDE`, `IMMICH_MEMORIES_TRIPS__HOMEBASE_LONGITUDE` | Home coordinates for trips and public holidays |
| `TZ` | Daily timer and log timezone |
| `IMMICH_MEMORIES_AUTH_USERNAME`, `IMMICH_MEMORIES_AUTH_PASSWORD` | Set both to enable Basic auth (password: 12+ characters, or startup warns); shipped `.env` support |
| `IMMICH_MEMORIES_STORAGE_SECRET` | Optional session signing key, generated when unset; 32+ random characters (`openssl rand -hex 32`) or the app refuses to start |
| `IMMICH_MEMORIES_SECRET_KEY` | Encrypt credentials saved in Settings; shipped `.env` support |
| `IMMICH_MEMORIES_UPLOAD__ENABLED`, `IMMICH_MEMORIES_UPLOAD__ALBUM_NAME` | Upload CLI/daily films; add to `environment:` |
| `IMMICH_MEMORIES_TIER` | `auto` by default; `basic`, `gpu` or `full` override (`nas` remains an alias for `basic`) |
| `IMMICH_MEMORIES_DATABASE_URL` | Optional PostgreSQL store; commented in Compose |

For service setup, use the [reader](../better/reader.md), [caption](../better/captions.md),
[inference](../better/inference.md), [render](../better/gpu-render.md) or [music](../better/music.md)
guide. Each gives the variables that service needs.

## The pattern

Every config key has the form `IMMICH_MEMORIES_<SECTION>__<FIELD>`: double underscores between
levels, with **no `ADVANCED` prefix**, even for YAML sections under `advanced:`.

```ini
IMMICH_MEMORIES_OUTPUT__RESOLUTION=1080p
IMMICH_MEMORIES_TITLE_SCREENS__FADE_COLOR=black
IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL=http://captioner:8092/v1
```

Lists and dictionaries take JSON:

```ini
IMMICH_MEMORIES_AUTH__ALLOWED_EMAILS='["me@example.com"]'
IMMICH_MEMORIES_ANALYSIS__EXCLUDE_FILENAME_PATTERNS='["RingVideo_*", "Screenshot*"]'
```

Setting a list replaces it. Copy any defaults you want to keep.
Find field names/defaults in the [config reference](../reference/config-reference.md).

## Shorthands

`IMMICH_URL`/`IMMICH_API_KEY` override the corresponding nested variables.
The Basic-auth shortcuts only activate when **both** values are present.

`OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are different: a resolved key already in `llm.api_key` (from YAML, stored settings or the nested variable) wins over
those generic shortcuts. To replace it explicitly, use `IMMICH_MEMORIES_LLM__API_KEY`.
The caption server needs its own `IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_API_KEY`.

The [exception reference](./reference/environment.md) lists all shortcuts and process variables.

## The secret key

Set `IMMICH_MEMORIES_SECRET_KEY` to save encrypted credentials from Settings or the CLI.
It is not the session signing key. [Generate and keep it](./config-file.md#secrets-in-the-database).
Keys supplied only through `.env` or YAML do not need database encryption.

## Precedence

Command flags win for that command, followed by the [configuration source order](./config-file.md#where-a-setting-comes-from).
The generic LLM key shorthands above are the exception to environment-first precedence.

## Compute tier

`IMMICH_MEMORIES_TIER` overrides `tier:` in YAML. The shipped Compose file maps `.env`'s
`TIER=basic` to `IMMICH_MEMORIES_DEPLOYMENT_TIER`; GPU/Full tier files request their own tier.
Deployment defaults remain editable through Settings. Use `IMMICH_MEMORIES_TIER` in the
container environment when you need a fixed override. [The tier guide](./requirements.md#which-tier-you-get)
explains what is detected.

### Immich connection

```ini
IMMICH_MEMORIES_IMMICH__API_VERSION="auto"
```

`auto` detects v2 or v3 at runtime; set `v2`/`v3` only to diagnose a proxy that breaks detection.
[Check the connection](./config-file.md#immich-api-compatibility) with `config test`.

## Link-local services

`IMMICH_MEMORIES_ALLOW_LINK_LOCAL_URLS=true` permits literal link-local addresses for configured
service URLs. It is off by default and only read from the process environment, never Settings.
See [configured service addresses](./network-security.md#configured-service-addresses).

## The ones that do not follow the pattern

Session/encryption keys, logging and local ACE-Step process settings have their own names.
See [Environment variable exceptions](./reference/environment.md).
Scheduled jobs do not inherit your shell's exports; keep the Immich connection in YAML.
