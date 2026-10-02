---
title: Upgrading
sidebar_label: Upgrading
---

# Upgrading

Read the [release notes](https://github.com/sam-dumont/immich-video-memory-generator/releases),
back up the store, then upgrade. Keep the backup for rollback: a newer release can migrate the
store to a revision older code will refuse.

## Docker

Back up while the old release is still running:

```bash
docker compose exec immich-memories immich-memories store backup
docker compose cp immich-memories:/home/immich/.immich-memories/backups ./backups
```

Keep that backup and manifest. If `docker-compose.override.yml` exists, change the app's `image:`
there; otherwise change it in `docker-compose.yml`. Replace `X.Y.Z` with the release tag,
without a `v` prefix:

```yaml
image: ghcr.io/sam-dumont/immich-video-memory-generator:X.Y.Z
```

The source Compose file ships `latest`; the install download may pin the current release in
an override. Keep app, inference and render worker version tags aligned. Then upgrade:

```bash
docker compose pull
docker compose up -d
docker compose exec immich-memories immich-memories models fetch
docker compose exec immich-memories immich-memories preflight
```

Config and films survive a recreate.
`models fetch` checks the new release's pins and downloads only changed files.

## uv / pip

```bash
immich-memories store backup
uv tool upgrade immich-memories
immich-memories models fetch
immich-memories preflight
```

For pip, keep the same extras:

```bash
pip install --upgrade "immich-memories[all]"
```

Use `all-mac` (and `auth` if added) for the corresponding Mac install.

## Kubernetes and Terraform

Back up, change the pinned image tag, apply, then run `models fetch` and `preflight` in the app
container. The init container only checks file existence, so it does not update changed pins.
See [Kubernetes upgrades](../kubernetes.md#upgrading-and-rollback) or
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

## Config compatibility

Unknown fields inside a known section are ignored; invalid values or unknown top-level sections
fail startup. A renamed setting can stop taking effect, so check the release notes.
The store upgrades its schema when opened. Keep a backup and its manifest from before an update;
if you roll back the app, restore the matching backup rather than downgrading a live schema.
Keep the app, inference image and render worker on matching version tags.

## Rollback

Restore the backup taken before upgrading if the newer release migrated the store.
Stop the app before restoring. [Container restore](../database.md#restore-in-a-container)
uses a one-off process, not `exec` in the running app.

For Docker, use this order. The backup and its manifest must be together on the mounted config
volume. Replace the example backup name with yours (`.dump` for PostgreSQL):

```bash
docker compose stop immich-memories
# Set image: to the old release in Compose (and its override, if present).
# Align inference and render worker tags with that release too.
docker compose pull
docker compose run --rm immich-memories immich-memories store restore \
  --from /home/immich/.immich-memories/backups/store-20260930T090000Z.db --force
docker compose up -d
docker compose exec immich-memories immich-memories preflight
```

Python:

```bash
uv tool install --force "immich-memories[all]==X.Y.Z"
```

Kubernetes/Terraform: restore the old image tag and apply, then restore the old store backup with
that release. Schema downgrades can drop tables and rows; the backup is the rollback.

## Inspecting the store before an upgrade

`store status`, `store backup`, `config show` and `preflight` read the existing schema without
upgrading it, including saved settings. A revision mismatch reports the actual and expected
schema. Back up first; `ui`, `generate`, `auto` and the explicit `store migrate` command upgrade
the configured store before writing.
