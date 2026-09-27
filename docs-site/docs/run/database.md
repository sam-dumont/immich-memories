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
back with it. `immich-memories store backup` dumps only this schema, independent of Immich's own
backup schedule, if you want the two to have separate retention.

## Run history and automation

Every run (its phases, delivery state and what it spent on the model), every nightly automation
attempt, the notification cooldown, the special-days catalogue, and the link from a run id to the
attempt directory it was cut from are store rows. That is what automation's cooldown and "already
made this memory" checks read, so wiping `cache.db` no longer re-films a memory you already have.
The attempt directories themselves, and the `run_metadata.json` beside each film, stay files.

Three kinds of work must never run twice at once: a nightly automation pass, an assembly, and a
film attempt. Each takes a lease first, and the store decides what a lease is:

- **SQLite:** a lock file beside `cache.db` (`.auto.lock`, `.lock`) or in the attempt directory
  (`.lease`). The operating system drops it when the process dies. One host, as SQLite always is.
- **PostgreSQL:** an advisory lock in the database, held on a connection the holder keeps open.
  The server drops it the moment that connection closes, a crash included. So several app
  instances, on as many machines as you like, can share one PostgreSQL store: whichever takes the
  lease runs, and the others say another run holds it. Two stores in one database (two schemas)
  never block each other.

## Managing the store

Five commands, all under `immich-memories store`. They act on whatever store the config points at
(`IMMICH_MEMORIES_DATABASE_URL`, or `database.url`, or the default SQLite file).

```mermaid
flowchart LR
    L["Legacy files<br/>(people.yaml, cache.db,<br/>annotations.sqlite, ...)"] -- "store import" --> S[("Store")]
    S -- "store backup" --> B["Backup file<br/>+ manifest.json"]
    B -- "store restore" --> S
    S -- "store copy --to URL" --> T[("Another store<br/>(SQLite or PostgreSQL)")]
    S -- "store status" --> R["Revision, row counts,<br/>size, import record"]
```

### `store status`

Backend, URL (password shown as `***`), schema, Alembic revision and whether it is at head, the
import record, rows per table, and the file size (SQLite, WAL included) or schema size
(PostgreSQL). It reads the database as it is: it never migrates it, and a SQLite file that does not
exist yet is reported, not created. A SQLite file on NFS, SMB or CIFS gets a warning line.

### `store backup [--to FILE]`

A consistent copy while the app keeps running:

- **SQLite:** `VACUUM INTO`, a compact single file.
- **PostgreSQL:** `pg_dump --format=custom --schema=<schema>`. Only the store's schema, never the
  rest of the database. The row counts and the dump read one snapshot, so the manifest describes
  the file exactly.

Without `--to` the file lands in `~/.immich-memories/backups/store-<UTC time>.db` (or `.dump`).
Beside it goes `<file>.manifest.json`: app version, Alembic revision, backend, schema, rows per table
and when it was taken. Keep the two together; a restore refuses a file without its manifest.
Existing files are never overwritten.

PostgreSQL backups need `pg_dump` on `PATH`, at least as new as the server. The Docker image ships
it (`postgresql-client`, currently 17, which dumps any server up to 17). On a uv/pip install, install
your distribution's `postgresql-client`; without it the command says so and stops.

### `store restore --from FILE [--force]`

Stop the app first: a restore replaces the database under it.

- It refuses a store that holds any row unless you pass `--force`.
- **SQLite:** the backup is copied beside the store file and swapped in, with the old `-wal` and
  `-shm` sidecars removed so they cannot be replayed into it.
- **PostgreSQL:** the store's schema is dropped and `pg_restore` rebuilds it. A backup restores under
  a different schema name too (it is renamed afterwards), as long as the original name is free in
  that database. A schema that holds tables that are not the store's is refused outright, so a
  mistyped `IMMICH_MEMORIES_DATABASE_SCHEMA=public` cannot take Immich with it.
- Afterwards the store is migrated to head and every table's row count is checked against the
  manifest. A backup from an older release restores and then upgrades like any other old store.

A SQLite backup restores into SQLite and a PostgreSQL one into PostgreSQL. To change backend,
restore into the backend the backup came from, then `store copy`.

### Moving from SQLite to PostgreSQL: `store copy --to URL`

```bash
immich-memories store copy --to postgresql+psycopg://immich_memories:change-me@postgres:5432/immich_memories
```

The target is migrated to head, then every table is copied in batches, parents before children,
in one transaction. Afterwards each table's row count and a content digest are compared between the
two stores, and any difference fails the command. A target that already holds rows is refused
unless you pass `--force`, which empties it first. `--schema` picks the PostgreSQL schema
(default: the configured one).

Then point `IMMICH_MEMORIES_DATABASE_URL` at the target and restart. The SQLite file stays where it
was; it is your way back. The same command works the other way, PostgreSQL to SQLite
(`--to sqlite:////data/store.db`).

### `store import [--from DIR] [--verify]`

Brings the files an install from before the store kept (`people.yaml`, `special-days.json`,
`cache.db`'s run history and asset scores, the run index, `annotations.sqlite`, `judgments.db`) into
the store. It runs by itself once, the first time a new version opens a store with no import record
while those files exist ([upgrading](./maintenance/upgrading.md#data-compatibility)); this command is
for running it by hand, from another directory, or again.

- The files are opened read-only and never changed or deleted.
- A record the store already holds is never replaced by an older one from a file.
- After each domain (people, then annotations and owner decisions, then run history) completes, its
  files' path, size, mtime and SHA-256 are recorded in the store. A rerun skips a domain whose files
  have not changed, and an interrupted import finishes where it stopped.
- `--verify` reads the files again and checks that every legacy record is in the store with the
  same values: exactly for owner decisions, people and special days, to within float rounding for
  model answers. Any difference is listed (table and key, never the values) and the command exits 1.

`--from` defaults to `IMMICH_MEMORIES_IMPORT_FROM`, then `database.import_from` in `config.yaml`, then
`~/.immich-memories`.
