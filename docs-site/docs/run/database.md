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

## Move to PostgreSQL

Create the target database/role using one of the [PostgreSQL modes](./reference/database.md), then:

```bash
immich-memories store copy --to 'postgresql+psycopg://immich_memories:password@postgres:5432/immich_memories'
```

The target must be empty unless you deliberately use `--force`. The command compares row counts
and content after copying. Point `IMMICH_MEMORIES_DATABASE_URL` at the target and restart.
The old SQLite file remains your way back. Protect URLs containing passwords like other secrets.

For an existing Docker Compose SQLite installation:

1. Download `docker-compose.postgres.yml` from the same release and set `POSTGRES_PASSWORD`
   in `.env`. Keep `COMPOSE_FILE` on the base file until the copy succeeds.
2. Start only PostgreSQL with the overlay, then stop the app. Copy using the base file so
   SQLite remains the source:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d --wait postgres
   docker compose -f docker-compose.yml stop immich-memories
   docker compose -f docker-compose.yml run --rm --no-deps immich-memories immich-memories store copy \
     --to 'postgresql+psycopg://immich_memories:password@postgres:5432/immich_memories'
   ```

3. Only after the copy and digest checks succeed, set
   `COMPOSE_FILE=docker-compose.yml:docker-compose.postgres.yml` in `.env` and run
   `docker compose up -d immich-memories`. Use the same password in the copy target URL and
   `POSTGRES_PASSWORD`. Keep the original SQLite file.

Enabling the app URL before copying makes PostgreSQL the source, so the original SQLite rows
would never be copied.


## 2. A separate PostgreSQL service

The separate `docker-compose.postgres.yml` adds the service, database URL, persistent volume
and readiness dependency. Set `POSTGRES_PASSWORD` and select both files with `COMPOSE_FILE`.
[Complete setup](./reference/database.md#2-a-separate-postgresql-service).

## 3. A separate database on your existing PostgreSQL instance

A dedicated database and role can share an instance with Immich without touching Immich's tables.
[SQL and connection setup](./reference/database.md#3-a-separate-database-on-your-existing-postgresql-instance).

## 4. A dedicated schema in Immich's own database

This is the expert option. Use a separate role/schema, not Immich's role or `public`.
A whole-Immich database restore also rewinds this schema.
[Isolation and restore details](./reference/database.md#4-a-dedicated-schema-in-immichs-own-database).

## Backup and restore {#managing-the-store}

[Storage and backups](./maintenance/storage-backups.md) has the full procedure for Python,
Docker and Kubernetes.

### Restoring in a container {#restore-in-a-container}

The [store command reference](./reference/store-commands.md#restore-in-a-container)
covers exact flags, what each command does to the schema, and container restore steps.

## Run history and automation

History, automation cooldowns and saved decisions are store rows. Attempt artifacts stay files.
SQLite uses local file locks; PostgreSQL uses advisory locks for background work across hosts.
Those leases protect CLI jobs, not the UI's in-memory workflow: keep one UI replica.

## Prepared facts

Normal upgrades reuse compatible facts. For producer versions or refreshing a known
bad answer, use [Detector facts and refreshes](./reference/detector-facts.md).
The [store command reference](./reference/store-commands.md) covers status, backup, restore and backend copies.
