---
title: Upgrading
sidebar_label: Upgrading
---

import InstallationFiles from '@site/src/components/InstallationFiles';

# Upgrading

Read the [release notes](https://github.com/sam-dumont/immich-memories/releases),
back up the store, then upgrade. Keep the backup for rollback: a newer release can migrate the
store to a revision older code will refuse.

## Server addresses

With authentication enabled, setting `auth.public_url` restricts requests to its hostname,
localhost and entries in `server.allowed_hosts`. If you also open the app by a LAN IP or
another hostname, add those addresses to `advanced.server.allowed_hosts` before upgrading.
Otherwise those requests receive HTTP 421.

An `immich.url` containing a username or password fails startup. Remove the credentials
from the URL and use `immich.api_key`. This also applies to each account's URL under
`immich.accounts`. If a reverse proxy requires URL credentials, give the app a private route
to Immich that accepts its API key.

## HTTP monitoring and request limits

For custom Kubernetes or Terraform deployments, set liveness to `/health/live` and readiness
to `/health/ready` before applying the new image. Both accept the pod IP in the probe's `Host`
header. The shipped manifests already use these paths.

A probe still using `/health` can receive HTTP 421 when `auth.public_url` or
`server.allowed_hosts` restricts the accepted hosts. This can keep the pod unready or make
Kubernetes restart it. Change the probe paths in the manifests or Terraform that own the
deployment. `/health` is a compatibility endpoint, not a readiness check.

With authentication enabled, `/health` and `/health/ready` keep their status codes and JSON
fields, but return `null` for operational details without a valid session. This includes
`configuration`, `immich` and `immich_reachable`. Use the HTTP status for readiness probes;
sign in to read the detailed diagnosis.

Every HTTP request accepts a body up to 4 MiB, including reads and sign-in pages. Larger requests
return HTTP 413. The soundtrack upload route keeps its separate 64 MiB file limit.

## Temporary working files

Keep cache and output directories on mounted storage with free space. Some working files,
including sampled video frames, use the system temporary directory, usually `/tmp`. They need
space there even when the cache volume has room. To move Python temporary files, set `TMPDIR`
to an existing writable directory on the intended mount before starting the app or worker.

See [temporary working files](./storage-backups.md#temporary-working-files) for the locations
and interrupted-run recovery.

## Job progress files

The web job directory becomes accessible only to the app account when the web server opens it.
Existing job history is kept, including older progress files. The parent cache folder keeps its
permissions.

Files written by `runs render --progress-file` are readable only by the writing account (0600).
Run a file watcher as that account. Old progress files outside the web job directory keep their
permissions until rewritten; restrict them yourself if they contain private output paths.

## API key permissions

Existing keys with **All** permissions continue to work. Preflight now warns about their broad
access; replace them with the [documented read set](../docker.md#the-api-key), adding upload
rights only when needed. Run `immich-memories config test` after changing a key.

Missing read permissions stop a cut before it starts. Missing upload or tagging permissions
keep the completed film locally with a download option and a specific delivery message.
Without `asset.delete`, previous versions remain in Immich. Partner keys need only read rights.

## Docker

Back up while the old release is still running:

```bash
docker compose exec immich-memories immich-memories store backup
docker compose cp immich-memories:/home/immich/.immich-memories/backups ./backups
```

Keep that backup and manifest. Download the new release's Compose assets and set
`IMMICH_MEMORIES_VERSION=X.Y.Z` in `.env`, without the `v` prefix. That one value selects matching
app, inference and standalone worker images; the CUDA file adds the inference CUDA suffix.
Keep your chosen `COMPOSE_FILE`, credentials and saved Settings. If you use a single-file export,
regenerate it with the new version and preserve its private settings key.

**Keep your existing host port when replacing or regenerating Compose files.** New 1.0.0 Compose
installs use host port **22830**; the 1.0.0 release candidates use **8080**. Copy your current `ports:`
mapping into the new file before starting it, including the bind address. For example, an
existing `127.0.0.1:8080:8080` can stay exactly that. The last number is the container port,
which remains 8080. An image-only upgrade keeps the existing mapping.

If you choose to move an existing install to 22830, update browser bookmarks and any host-based
reverse proxy, tunnel or firewall rule that names the old port. Proxies that connect directly
to the app container still use 8080. Then upgrade:

```bash
docker compose pull
docker compose up -d
docker compose exec immich-memories immich-memories models fetch
docker compose exec immich-memories immich-memories preflight
```

Config and films survive a recreate.
`models fetch` checks the new release's pins and downloads only changed files.

## uv / pip

Back up before changing the installed package:

```bash
immich-memories store backup
```

The native install pins a version. `uv tool upgrade` keeps that pin, so replace it by running the
current package command for your platform:

<InstallationFiles kind="native" />

Keep any extras you added: on Apple Silicon with OIDC, change `[all-mac]` to `[all-mac,auth]` and
retain `--with laya-mlx`. This updates the app environment and leaves its configuration and store
in place. See [uv's version-constraint rule](https://docs.astral.sh/uv/guides/tools/#upgrading-tools).

For pip, run `python -m pip install --upgrade` inside the app's virtual environment with the same
quoted package and version specification shown above. Keep the same extras; Apple Silicon GPU/Full
also needs `laya-mlx` in that environment.

Then verify the new model pins and installation:

```bash
immich-memories models fetch
immich-memories preflight
```

## Kubernetes and Terraform

Back up, change the pinned image tag, apply, then run `models fetch` and `preflight` in the app
container. The base init container skips fetching when its required paths are present, so changed
pins need the explicit fetch. The generated GPU setup runs `models fetch --detectors --laya`
whenever its model init container runs, verifying existing artifact digests.
See [Kubernetes upgrades](../reference/kubernetes-operations.md#upgrading-and-rollback) or
[Terraform upgrades](../terraform.md#upgrading).

## Upgrading Immich from v2 to v3

Leave version detection on auto:

```yaml
immich:
  api_version: auto
```

After upgrading Immich:

```bash
immich-memories config test
```

This read-only check prints the resolved v2/v3 contract. Overrides are for troubleshooting a
proxy, not an upgrade step. Originals are unchanged.

### Immich 3.3

- **Country names.** Immich 3.3 stores GeoNames' English country names ("The Netherlands",
  "Turkey", "Cabo Verde"). The app reads those and the earlier names alike, so titles and captions
  still translate the country.
- **Stacks.** Add `stack.read` to the key if you want a stack (an edit and its original, a burst)
  to play as its top picture. It is optional: without it the run logs one warning per account and
  treats every stacked picture as its own candidate.
- **Native people sharing** is tested on 3.3.0 final. It also accepts 3.3.0-rc.1, later
  3.3.0 release candidates and every 3.3 release. See [A second Immich account](../multi-account.mdx).

## Config compatibility

Unknown fields inside a known section are ignored; invalid values or unknown top-level sections
fail startup. A renamed setting can stop taking effect, so check the release notes. A removed key
is dropped with a warning at startup that names it and says what to do, for example:

```text
Ignoring config keys that no longer exist in config.yaml; delete them to silence this:
  audio.music_volume_db: nothing read it; remove it from your config
  defaults.output_orientation: the CLI picks the orientation; remove it from your config
```

Delete the key once you've read why.

The low-end tier is `basic`. A `tier: nas` in YAML, `IMMICH_MEMORIES_TIER=nas`,
`IMMICH_MEMORIES_DEPLOYMENT_TIER=nas` or a saved Settings value of `nas` stops startup with
`tier 'nas' is now called 'basic': set tier: basic`. Change the value to `basic`.

The reader only runs with `advanced.llm.enabled: true`. A config that sets `advanced.llm.base_url`,
`model` or another reader field without it keeps the reader off: model titles, music mood and model
selection stay off, startup logs a warning naming the fields it found (never their values), and
`preflight` reports **Reader configured but disabled**. Add `enabled: true` under `advanced.llm`.
See [enabling a reader](../config-file.md#enabling-a-reader).

The store upgrades its schema when opened. Keep a backup and its manifest from before an update;
if you roll back the app, restore the matching backup rather than downgrading a live schema.
Keep the app, inference image and render worker on matching version tags.

## Rollback

Restore the backup taken before upgrading if the newer release migrated the store.
Stop the app before restoring. [Container restore](./storage-backups.md#restore)
uses a one-off process, not `exec` in the running app.

For Docker, use this order. The backup and its manifest must be together on the mounted config
volume. Replace the example backup name with yours (`.dump` for PostgreSQL):

```bash
docker compose stop immich-memories
# Set IMMICH_MEMORIES_VERSION in .env to the old release (no v prefix).
# For single-file/custom installs, set matching app, inference and worker image tags.
docker compose pull
docker compose run --rm immich-memories immich-memories store restore \
  --from /home/immich/.immich-memories/backups/store-20260930T090000Z.db --force
docker compose up -d
docker compose exec immich-memories immich-memories preflight
```

Python:

```bash
uv tool install --force --python 3.12 "immich-memories[all]==X.Y.Z"
```

Kubernetes/Terraform: restore the old image tag and apply, then restore the old store backup with
that release. Schema downgrades can drop tables and rows; the backup is the rollback.

## Inspecting the store before an upgrade

`store status`, `store backup`, `config show` and `preflight` read the existing schema without
upgrading it, including saved settings. A revision mismatch reports the actual and expected
schema. Back up first; `ui`, `generate`, `auto` and the explicit `store migrate` command upgrade
the configured store before writing.
