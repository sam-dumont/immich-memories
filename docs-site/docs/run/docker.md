---
title: Docker Compose
---

# Docker Compose

Docker Compose runs the app beside your existing Immich server. Basic uses one container;
GPU and Full add model services. This is the recommended container install.
You need Docker Compose v2 and [4 GB free for the app](./requirements.md). On a NAS, check the
[NAS notes](./nas.md) for folder permissions and device access.

## Install

Follow [Quick start](../get-started/quick-start.md) and select **Basic**, **GPU** or **Full**.
It covers the release files, Immich connection, access, model preparation and first film.
For a single file to paste into a stack editor, use the [setup builder](/setup).

This page covers operating that installation. [Installation help](../reference/installation-help.md)
has port, permissions and startup fixes.

### 1. Get the files

Use the [download block for your tier](../get-started/quick-start.md#1-download-the-files).

### 2. Connect Immich

Set the [Immich connection](../get-started/quick-start.md#2-connect-immich) and use the
[API-key permissions](#the-api-key) below. Home coordinates and film language can be set after
installation in [Settings](../get-started/after-install.md).

### 3. Start and check

Run the [start and model commands](../get-started/quick-start.md#3-start-and-download-the-local-models)
from the same Compose project directory.

### 4. Open the app

[Open the app and make a film](../get-started/quick-start.md#4-open-the-app).

### When a step is missing

Use [Installation help](../reference/installation-help.md#read-preflight).

## Reaching the UI from another machine

The shipped mapping is `127.0.0.1:8080:8080`: only the host can reach it.
From your desktop, a tunnel needs no port change:

```bash
ssh -L 8080:localhost:8080 you@your-server
```

Open `http://localhost:8080` on the desktop.

For LAN access, set these in `.env`:

```ini
IMMICH_MEMORIES_AUTH_USERNAME=admin
IMMICH_MEMORIES_AUTH_PASSWORD=choose-a-long-password
UI_BIND_ADDRESS=0.0.0.0
```

`UI_BIND_ADDRESS` is the switch: the shipped mapping is `${UI_BIND_ADDRESS:-127.0.0.1}:8080:8080`,
so there is no need to edit it. Run `docker compose up -d`, then open `http://your-server:8080`.
If 8080 is taken, change the left-hand 8080 in the mapping, for example `8081:8080`.

To check that auth is on, call a protected route without logging in, from another machine:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://your-server:8080/api/v1/settings
```

It answers 401 without a session and 200 after login. `/health/ready` is anonymous on purpose
and returns the app version and whether Immich is reachable, so it isn't an auth test.

This port speaks plain HTTP: the password and session cookie cross your LAN in the clear. For
TLS, put a reverse proxy in front and keep `UI_BIND_ADDRESS=127.0.0.1`
([Authentication](./authentication.mdx)).

:::caution This app can access your library
Authentication is disabled by default. Enable it before exposing the port.
Keep one UI replica.
:::

For OIDC or a proxy with HTTPS, see [Authentication](./authentication.mdx).

### Stack editor LAN access {#stack-editor-lan-access}

The builder's **Single file for a stack editor** output has no `.env`. Before deploying it on
a trusted LAN, set these entries directly under the app service's existing `environment:`:

```yaml
IMMICH_MEMORIES_AUTH_USERNAME: admin
IMMICH_MEMORIES_AUTH_PASSWORD: replace-with-your-own-long-password
```

Choose a password of at least 12 characters. In the same app service, change its `ports:` entry
from `127.0.0.1:8080:8080` to `0.0.0.0:8080:8080` (keep your chosen host port if it differs).
Deploy the stack, open `http://your-server-address:8080`, and sign in. The container manager's
login does not protect this port. This is HTTP on your LAN; for encrypted access, keep localhost
and use the [SSH tunnel above](#reaching-the-ui-from-another-machine) or
[HTTPS proxy setup](./authentication.mdx#behind-a-reverse-proxy-with-tls).

## The API key

In Immich, open **Account Settings > API Keys > New API Key**. Select these ten read
permissions to make films. Add the upload set only on the account that receives finished films.
Partner accounts need the read set only.

| Read permission | Used for |
|---|---|
| `user.read` | Checking the account and connection |
| `asset.read` | Metadata, asset details and timeline selection |
| `asset.statistics` | Counting pictures with people |
| `asset.view` | Thumbnails and video playback |
| `asset.download` | Downloading original media, including for a render worker |
| `face.read` | Face boxes |
| `person.read` | People, their details and thumbnails |
| `person.statistics` | Picture counts for a person |
| `album.read` | Finding albums |
| `map.search` | Finding the home country from Immich's own map data |

| Optional upload permission | Used for |
|---|---|
| `asset.upload` | Uploading the film and checking for duplicate uploads |
| `tag.create` | Creating or finding the app's generated-film tag |
| `tag.asset` | Attaching that tag to the film |
| `album.create` | Creating the destination album |
| `albumAsset.create` | Adding the film to the album |

`asset.delete` is separate and optional. It lets the app move a previous render of the same
recipe to Immich's trash after the replacement succeeds. It never authorizes a hard delete
through this app. Originals are not changed.

`stack.read` is separate and optional too. It lets the app fold a stack (an edit and its
original, a burst) into its top picture before selection, so only one of them ships, and a star
on any picture of the stack counts for it. Without it, `GET /stacks` answers 403, the run logs one
warning for that account, and every stacked picture is read as its own candidate.

Do not add `timeline.read`, `tag.read`, or album-update permissions to this minimum.
Timeline routes use `asset.read`. The app reads the key's own permission list through
`GET /api-keys/me`, which needs API-key authentication but no extra permission.

Run `immich-memories preflight` or `immich-memories config test` after creating the key.
A missing read permission is an error naming the missing permissions, and a cut will not start.

Missing upload rights leave the film usable. The Render panel explains why its upload option
is unavailable. If upload was requested through the CLI, saved settings or automation, the film
is still rendered and kept locally; the run reports what could not be uploaded and offers
**Download**. The CLI prints the local path.

With partial upload rights, the app performs the permitted steps and reports the missing ones.
For example, `asset.upload` without tag permissions can upload a film but cannot mark it as
this app's own. On Immich v3 that untagged film could be selected as source footage later.
The local film is kept whenever uploading, tagging or album filing is incomplete.
Without `asset.delete`, the new upload can succeed and the previous version stays in Immich.

**All** is not recommended: that key can change or delete the whole library. Existing All keys
continue to work, but preflight warns and points back to this smaller permission set.

## Using the CLI

The CLI is inside the container. Commands elsewhere in these docs use this prefix:

```bash
docker compose exec immich-memories immich-memories generate --year 2025 --month 6
```

An optional alias saves typing:

```bash
alias im='docker compose exec immich-memories immich-memories'
im preflight
```

## Films into Immich

Local films appear in `./output`. The web Render panel has an upload checkbox.
To upload CLI and daily films by default, add this to the service's `environment:` block:

```yaml
      IMMICH_MEMORIES_UPLOAD__ENABLED: "true"
      IMMICH_MEMORIES_UPLOAD__ALBUM_NAME: "Memories"
```

Run `docker compose up -d`. A line in `.env` alone does not pass an arbitrary variable to the
container. [Environment variables](./environment-variables.md) explains the rule.
After confirmed upload, the local film and its run directory are removed.
[What Immich sees](./privacy.md#what-immich-sees) lists the writes.

## Next to your Immich stack

You can put the `immich-memories` service in Immich's Compose file. Add
`immich-memories-config:` to its top-level `volumes:`, set
`IMMICH_URL=http://immich-server:2283`, and add `depends_on: [immich-server]`.
The service then reaches Immich over that stack's internal network.

## Add-on services

For a fresh GPU or Full installation, use the tier tab in [Quick start](../get-started/quick-start.md).
The guides below cover changing individual services on an existing install.

<Diagram name="deploy-compose" headline="Start with one container. Add a file for each upgrade." />
| Want | Setup |
|---|---|
| GPU picture preparation | [Inference service](../better/inference.md), `docker-compose.gpu.yml` |
| Image captions | [Caption server](../better/captions.md), `docker-compose.gpu.yml` |
| A text model | [Reader](../better/reader.md) |
| Faster video encoding | [Hardware encoding](./hardware.md) |
| Rendering on another box | [Render worker](../better/gpu-render.md) |
| Generated music | [Music](../better/music.md) |

### Reaching a model server

A server on the Docker host is `host.docker.internal`, not `localhost`:

For an existing install, set the reader URL to `http://host.docker.internal:8000/v1` and the
caption URL to `http://host.docker.internal:8092/v1` in Settings. Full also needs the reader's
served model and explicit enable switch. The [setup builder](/setup) supplies those values as
editable defaults for a fresh install.

Docker Desktop resolves that name. On Linux, add this to the service and have the model server
listen on an address reachable from the bridge, such as `0.0.0.0`:

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

## The product tier in compose {#the-preparation-tier-in-compose}

The base requests Basic through `TIER=basic`. The GPU and Full tier files request their respective
tiers. Preflight checks whether the selected hardware and services can satisfy that request.
Saved Settings can override these deployment defaults. See [tier requirements](./requirements.md#the-preparation-tier).
Keep `IMMICH_MEMORIES_EDITORIAL__PREPARATION__DETECTOR_CACHE_DIR` on the persistent volume when
writing your own service block, so detector downloads survive a recreate.

## Resources

The default 4 GB limit suits 1080p. Use 8 GB for 4K on GPU/Full; Basic stays capped at 1080p.
The file sets no CPU quota because Synology kernels can refuse `cpus:`. Use
[`cpuset` if needed](./nas.md#do-not-use-cpus-on-a-synology).

## Daily automation

Add these two lines to the service's `environment:` block, set `TZ` in `.env`, and recreate:

```yaml
      IMMICH_MEMORIES_AUTOMATION__ENABLED: "true"
      IMMICH_MEMORIES_AUTOMATION__DAILY_AT: "09:00"
```

The running UI makes one eligible memory a day. No cron required.
[Automate it](../make/automate.md) covers selection, uploads, retries and external triggers.

## Health check and logs

```bash
docker inspect --format='{{.State.Health.Status}}' immich-memories
docker compose logs -f immich-memories
```

The image probes `/health/live`; monitoring should use `/health/ready`.
[Diagnostics](./maintenance/health-logs-cache.md) covers per-run logs and preflight.

## What to keep

Keep the named config volume and `./output`. The expensive data is `store.db`: prepared facts,
people, settings, review decisions and run history. [Back up the store](./database.md#managing-the-store)
and keep any `IMMICH_MEMORIES_SECRET_KEY` you use for saved credentials.

## The store: SQLite or PostgreSQL

SQLite on the config volume is the default. You do not need PostgreSQL to make films.
[Database and backups](./database.md) covers both backends and moving an install.

## Updating

Follow [Upgrading](./maintenance/upgrading.md#docker): back up, pull the image, recreate,
fetch the current model pins and run preflight.

## Disk

The preview/video caches default to 10 GB each. Uploaded films are removed locally after confirmed
delivery; local-only or failed deliveries keep their files. [Storage and caches](./maintenance/health-logs-cache.md#caches)
covers sizing and cleanup.

## Hardening

<details>
<summary>Run with a read-only root filesystem</summary>

Uncomment the shipped block:

```yaml
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:size=2G
      - /home/immich/.cache:size=1G
```

The persistent config volume keeps the session signing key. For 4K, allow more temporary space
(e.g. 8 GB); intermediates can exceed 2 GB. Tmpfs uses memory, so size it with the container limit
in mind.

</details>

## Custom music

Upload a track in the web Render panel. For CLI runs, bind-mount a music directory and use
`--music /app/music/track.mp3`.

Add this alongside the app's existing `volumes:` entries, then run `docker compose up -d`:

```yaml
      - ./music:/app/music:ro
```

Put `track.mp3` in `./music` on the host:

```bash
docker compose exec immich-memories immich-memories generate --year 2025 --music /app/music/track.mp3
```

## Building the image

For a source checkout, `make docker` fills in the version and git metadata. The normal install
uses the published image. `INSTALL_EXTRAS=none make docker` builds a slim image without the
classifiers needed for films.

## Stop or remove this installation

[Stop, reset and uninstall](./lifecycle.md) separates retaining data for reinstall from deleting app state.
