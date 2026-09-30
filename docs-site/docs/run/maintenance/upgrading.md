---
title: Upgrading
sidebar_label: Upgrading
---

# Upgrading

Read the [release notes](https://github.com/sam-dumont/immich-video-memory-generator/releases),
back up the store, then upgrade. Keep the backup for rollback: a newer release can migrate the
store to a revision older code will refuse.

## Docker

```bash
docker compose exec immich-memories immich-memories store backup
docker compose pull
docker compose up -d
docker compose exec immich-memories immich-memories models fetch
docker compose exec immich-memories immich-memories preflight
```

Copy the backup and manifest off the volume. Config and films survive a recreate.
`models fetch` checks the new release's pins and downloads only changed files.
Pin `image:` to a release tag if you want controlled upgrades; tags have no `v` prefix.

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
For retired settings/commands and pre-store imports, see [Migrating older installs](../reference/migration.md).

## Data compatibility

The store migrates forward when opened. Older file-based installs are imported once, without
changing or deleting their source files. Verify an import with:

```bash
immich-memories store import --verify
```

The [migration notes](../reference/migration.md#data-compatibility) list what is imported and how
to point at an older data directory. Keep original files until verification passes.

## Rollback

Restore the backup taken before upgrading if the newer release migrated the store.
Stop the app before restoring. [Container restore](../database.md#restore-in-a-container)
uses a one-off process, not `exec` in the running app.

Docker: set the old image tag, pull and recreate:

```yaml
image: ghcr.io/sam-dumont/immich-video-memory-generator:X.Y.Z
```

```bash
docker compose pull
docker compose up -d
```

Python:

```bash
uv tool install --force "immich-memories[all]==X.Y.Z"
```

Kubernetes/Terraform: restore the old image tag and apply, then restore the old store backup with
that release. Schema downgrades can drop tables and rows; the backup is the rollback.

A release from before the store reads the untouched legacy files, but cannot see new decisions
or runs saved only in the store.

## Removed commands

[The migration table](../reference/migration.md#removed-commands) maps retired commands to their
replacements. For a fixed-date film, use a system schedule as in [Automation](../../make/automate.md).
