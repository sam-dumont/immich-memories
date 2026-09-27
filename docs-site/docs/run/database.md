---
title: Database and the store
---

# Database and the store

The store holds the parts of a memory that are not files: people, aliases and confirmations,
owner decisions, model answers someone paid for, run history, and settings the UI edits. It
defaults to a SQLite file next to `config.yaml`. Nothing else needs installing for that default,
and it is not a fallback: SQLite is a first-class backend, and so is PostgreSQL when you want one.
Media, previews, thumbnails and per-attempt artifacts stay files either way; the cache (derived
analysis, hashes, scene prints, geocoding) is always local SQLite and is never migrated or backed
up.

Four ways to point it, in increasing order of "I already run PostgreSQL for something else":

```mermaid
flowchart LR
    A["1. SQLite file<br/>(default)"] --> B["2. Separate PostgreSQL<br/>service"]
    B --> C["3. Separate database on<br/>your existing PostgreSQL"]
    C --> D["4. Dedicated schema in<br/>Immich's own database"]
```

All four are the same `IMMICH_MEMORIES_DATABASE_URL` setting (unset means mode 1); nothing else in
the app changes. `store copy --to <url>` moves an existing SQLite store to any of the others.

## 1. SQLite file on local disk (default)

`sqlite:///~/.immich-memories/store.db`, expanded per call so a container's `HOME` still works.
This is the right choice for the common case: one host, one container, one writer. WAL mode,
`busy_timeout=30000` and short write transactions make it hold up fine at the scale this app runs
at (a library in the tens of thousands of assets, not millions).

**SQLite's rules, and why they exist:**

- **Local disk only.** Opening the file over NFS, SMB or CIFS is refused unless you set
  `IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE=1`, and even then it warns on every start. WAL mode needs
  shared memory between the writer and the lock file, which a network filesystem does not give two
  hosts. This is not a permissions problem you can work around: the file corrupts silently, and you
  find out when a read comes back wrong.
- **One writer host.** A second process on a second host writing the same file, even on local
  disk mounted twice, is the same problem. On Kubernetes this is why the CronJobs in
  `deploy/kubernetes/base/job.yaml` call the running Deployment's `POST /api/trigger` route instead
  of mounting the store PVC themselves: see [Kubernetes](./kubernetes.md#database).

## 2. A separate PostgreSQL service

`docker-compose.yml` ships a commented `postgres` service (`postgres:16`, pinned by digest) and a
commented `IMMICH_MEMORIES_DATABASE_URL` line on the app service. Uncomment both, set
`POSTGRES_PASSWORD` in `.env`, and `docker compose --profile postgres up -d`. On Kubernetes,
`deploy/kubernetes/overlays/postgres` does the equivalent: it is not referenced by
`base/kustomization.yaml`, so applying `base` alone keeps SQLite, and applying the overlay points
the Deployment at a `database-secret.yaml` you fill in yourself; it does not run PostgreSQL for
you. Terraform: set `database_url` (and, only if you share the instance, `database_schema`), both
empty by default.

```
IMMICH_MEMORIES_DATABASE_URL=postgresql+psycopg://immich_memories:change-me@postgres:5432/immich_memories
```

Plain PostgreSQL 14+. No extensions, no `vchord`, no pgvector: every vector comparison in this app
is exact numpy over a small candidate set (one film, one story, a 14-day window), so there is no
extension to install and no extension to keep in step with an upstream image.

## 3. A separate database on your existing PostgreSQL instance

The same URL, pointed at a database on an instance you already run for something else (including
Immich's own PostgreSQL container, if you want to reuse it without touching Immich's schema):

```
IMMICH_MEMORIES_DATABASE_URL=postgresql+psycopg://immich_memories:change-me@immich-postgres:5432/immich_memories
```

Create the database and a role scoped to it first:

```sql
CREATE ROLE immich_memories WITH LOGIN PASSWORD 'change-me';
CREATE DATABASE immich_memories OWNER immich_memories;
```

Nothing here reads or writes Immich's own database. This mode exists for hosts that already pay
for one PostgreSQL instance and want a second logical database on it rather than a second
container.

## 4. A dedicated schema in Immich's own database

Point the URL at Immich's database, and set the schema so the store's tables land somewhere that
is not `public`:

```
IMMICH_MEMORIES_DATABASE_URL=postgresql+psycopg://immich_memories:change-me@immich-postgres:5432/immich
IMMICH_MEMORIES_DATABASE_SCHEMA=immich_memories
```

Create the role and schema, with no grants on anything Immich owns:

```sql
CREATE ROLE immich_memories WITH LOGIN PASSWORD 'change-me';
CREATE SCHEMA immich_memories AUTHORIZATION immich_memories;
```

That is the whole grant. The role owns its own schema and nothing else: no `GRANT` on `public`, no
grant on any Immich table, no cross-schema foreign key, no search-path change on Immich's own
role. Alembic's version table (`alembic_version`) lives inside `immich_memories`, and autogenerate
is scoped to this app's own `MetaData`, so a migration here never touches Immich's tables and an
Immich migration never touches this schema. No extensions are needed for either side, so there is
nothing to reconcile between the two.

**The one thing this mode does not protect against:** a whole-database restore of Immich (`pg_dump
-d immich` or a snapshot restore) restores every schema in that database, this one included. If you
restore Immich from a backup taken before a memory run, that run's decisions and banked answers go
back with it. `pg_dump -n immich_memories` backs up only this schema, independent of Immich's own
backup schedule, if you want the two to have separate retention.

## Run history and automation

Every run (its phases, delivery state and what it spent on the model), every nightly automation
attempt, the notification cooldown, the special-days catalogue, and the link from a run id to the
attempt directory it was cut from are store rows. That is what automation's cooldown and "already
made this memory" checks read, so wiping `cache.db` no longer re-films a memory you already have.
The attempt directories themselves, and the `run_metadata.json` beside each film, stay files.

Two things still coordinate through lock files beside `cache.db` rather than through the store: a
render takes `.lock`, and a nightly automation pass takes `.auto.lock`, so the scheduler inside the
web UI and a CLI run on the same host never start the same work twice. That holds on PostgreSQL
too. It does not stretch across hosts: two machines running automation against one PostgreSQL store
is not supported, which is also why the Kubernetes CronJobs trigger the running pod instead of
running their own.

## Backups

`store backup` works the same way on either backend: `VACUUM INTO` for SQLite, `pg_dump -n
immich_memories` (or `-d` for the whole database, modes 2 and 3) for PostgreSQL. Both write a
manifest recording the app version, the Alembic revision and the backend, so `store restore` can
tell a mismatched backup apart from a compatible one before it overwrites anything.
