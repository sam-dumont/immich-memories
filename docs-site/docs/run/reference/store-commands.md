---
title: Store command reference
---

# Store command reference

For exact backup, restore and backend-copy behavior. Start with
[Database and backups](../database.md) for the procedure.

## Managing the store

Five routine commands, all under `immich-memories store`. They act on whatever store the config points at
(`IMMICH_MEMORIES_DATABASE_URL`, or `database.url`, or the default SQLite file).



### `store status`

Backend, URL (password shown as `***`), schema, Alembic revision and whether it is at head, the
import record, rows per table, and the file size (SQLite, WAL included) or schema size
(PostgreSQL). It reads the database as it is: it never migrates it, and a SQLite file that does not
exist yet is reported, not created. A SQLite file on NFS, SMB or CIFS gets a warning line.

### `store migrate`

Upgrade the configured store to this release's schema. `ui`, `generate` and `auto` also upgrade
before writing. `store status`, `store backup`, `config show` and `preflight` load saved settings
without migrating and report an actual/expected revision mismatch. A store from before saved
settings existed uses configuration defaults; an unreadable settings table stops configuration
loading instead of silently losing overrides.

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
- **PostgreSQL:** restore first requires `CREATE` on the database and refuses without changing
  the existing store if that privilege is missing. The store's schema is dropped and `pg_restore` rebuilds it. A backup restores under
  a different schema name too (it is renamed afterwards), as long as the original name is free in
  that database. A schema that holds tables that are not the store's is refused outright, so a
  mistyped `IMMICH_MEMORIES_DATABASE_SCHEMA=public` cannot take Immich with it.
- Afterwards the store is migrated to head and every table's row count is checked against the
  manifest. A backup from an older release restores and then upgrades like any other old store.

A SQLite backup restores into SQLite and a PostgreSQL one into PostgreSQL. To change backend,
restore into the backend the backup came from, then `store copy`.

#### Restore in a container {#restore-in-a-container}

In a container the app is the process that holds the store, so `exec` into it is the wrong place.
Stop it and run the restore in a one-off container on the same volumes.

**Docker Compose:**

```bash
docker compose stop immich-memories
docker compose run --rm immich-memories immich-memories store restore \
  --from /home/immich/.immich-memories/backups/store-<UTC time>.db --force
docker compose up -d
```

**Kubernetes and Terraform:** suspend the installed CronJobs first (record which were active), then scale the Deployment to 0, run a copy of the one-off `generate` Job in
`deploy/kubernetes/base/job.yaml` with its command replaced by
`immich-memories store restore --from /home/immich/.immich-memories/backups/<file> --force` (add the
database Secret to it when the store is on PostgreSQL), then scale back to 1:

```bash
kubectl -n immich-memories get cronjob -l app.kubernetes.io/name=immich-memories
kubectl -n immich-memories patch cronjob immich-memories-auto -p '{"spec":{"suspend":true}}'
kubectl -n immich-memories patch cronjob immich-memories-monthly -p '{"spec":{"suspend":true}}'
kubectl -n immich-memories scale deploy/immich-memories --replicas=0
kubectl -n immich-memories wait --for=delete pod -l 'app.kubernetes.io/name=immich-memories,!job-name,!batch.kubernetes.io/job-name' --timeout=120s
kubectl -n immich-memories apply -f restore-job.yaml && kubectl -n immich-memories wait --for=condition=complete job/<name>
kubectl -n immich-memories scale deploy/immich-memories --replicas=1
```

Wait for any already-running scheduled Job to finish before restoring. After a successful restore,
resume only CronJobs that were active before maintenance with `spec.suspend=false`.

On a uv or pip install, stop `immich-memories ui` and run the restore from a shell, outside the time
the daily job fires.

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
