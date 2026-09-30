---
title: Database and backups
---

# Database and backups

Keep the store. It holds your people, settings, review decisions, prepared model answers and run
history. Losing it means preparing the library again and losing your saved decisions.
Previews, downloaded clips and finished films are separate files.

## 1. SQLite file on local disk (default)

The default is `~/.immich-memories/store.db`. No database server to install.
Docker keeps it on the config volume; Kubernetes keeps it on the data/cache PVC.

Use local disk and one writer host. NFS, SMB and CIFS are refused because SQLite WAL locking
needs local shared memory. `IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE=1` bypasses that check with a
warning; it does not make multi-host writing safe.

PostgreSQL is optional. It does not make the UI multi-replica.

## Managing the store

### Back up

```bash
immich-memories store backup
```

Docker:

```bash
docker compose exec immich-memories immich-memories store backup
docker compose cp immich-memories:/home/immich/.immich-memories/backups ./backups
```

The app can keep running. The command creates a `.db` (SQLite) or `.dump` (PostgreSQL), plus a
`.manifest.json`, under `~/.immich-memories/backups/`. Keep both together and copy them off the
host. Restore requires the manifest.

Also keep:

- `config.yaml` and deployment files;
- `IMMICH_MEMORIES_SECRET_KEY`, if used for saved credentials;
- finished films you keep locally.

PostgreSQL backups need `pg_dump` at least as new as the server. The Docker image includes client
17, so a newer PostgreSQL server needs a matching client. Python installs need client tools on
`PATH`.

### Restore in a container {#restore-in-a-container}

Stop the app first. A restore replaces its database.

```bash
docker compose stop immich-memories
docker compose run --rm immich-memories immich-memories store restore \
  --from /home/immich/.immich-memories/backups/store-20260930T090000Z.db --force
docker compose up -d
```

The filename above is an example; use your actual backup (`.dump` for PostgreSQL). Keep its manifest beside it.
`--force` permits replacing a non-empty store.

For Kubernetes, scale the Deployment to zero and run a one-off restore Job on the same volumes
(and database Secret, when applicable), then scale back to one. The
[store command reference](./reference/store-commands.md#restore-in-a-container) gives the Job
procedure. Do not `exec` a restore into the running app.

A SQLite backup restores into SQLite; a PostgreSQL backup restores into PostgreSQL.
To change backend, restore first, then copy.

### Move to PostgreSQL

Create the target database/role using one of the [PostgreSQL modes](./reference/database.md), then:

```bash
immich-memories store copy --to 'postgresql+psycopg://immich_memories:password@postgres:5432/immich_memories'
```

The target must be empty unless you deliberately use `--force`. The command compares row counts
and content after copying. Point `IMMICH_MEMORIES_DATABASE_URL` at the target and restart.
The old SQLite file remains your way back. Protect URLs containing passwords like other secrets.

## 2. A separate PostgreSQL service

Compose ships a commented service, database URL and volume. Enable all three and set
`POSTGRES_PASSWORD`/`COMPOSE_PROFILES=postgres` in `.env`.
[Complete setup](./reference/database.md#2-a-separate-postgresql-service).

## 3. A separate database on your existing PostgreSQL instance

A dedicated database and role can share an instance with Immich without touching Immich's tables.
[SQL and connection setup](./reference/database.md#3-a-separate-database-on-your-existing-postgresql-instance).

## 4. A dedicated schema in Immich's own database

This is the expert option. Use a separate role/schema, not Immich's role or `public`.
A whole-Immich database restore also rewinds this schema.
[Isolation and restore details](./reference/database.md#4-a-dedicated-schema-in-immichs-own-database).

## Run history and automation

History, automation cooldowns and saved decisions are store rows. Attempt artifacts stay files.
SQLite uses local file locks; PostgreSQL uses advisory locks for background work across hosts.
Those leases protect CLI jobs, not the UI's in-memory workflow: keep one UI replica.

## Detector cache contract for 1.0.0

Normal upgrades reuse compatible facts. For producer versions, migrations or refreshing a known
bad answer, use [Detector facts and refreshes](./reference/detector-facts.md).
The [store command reference](./reference/store-commands.md) covers status, copy and legacy imports.
