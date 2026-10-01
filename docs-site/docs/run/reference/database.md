---
title: PostgreSQL deployment modes
---

# PostgreSQL deployment modes

SQLite on local disk is the default. Use PostgreSQL when your storage topology needs it or you
already operate an instance. The UI still stays at one replica.
For everyday backups, start with [Database and backups](../database.md).

## 2. A separate PostgreSQL service

`docker-compose.yml` ships a commented `postgres` service (`postgres:16`, pinned by digest), a
commented `IMMICH_MEMORIES_DATABASE_URL` line on the app service, and a commented
`immich-memories-postgres-data` volume at the bottom. Uncomment all three, then in `.env`:

```bash
POSTGRES_PASSWORD=a-long-random-password
COMPOSE_PROFILES=postgres
```

and `docker compose up -d`. The service sits behind the `postgres` profile, and
`COMPOSE_PROFILES` turns it on for every later `up` too, so an update with a plain
`docker compose up -d` does not leave the app without its database. On Kubernetes,
`deploy/kubernetes/overlays/postgres` does the equivalent: it is not referenced by
`base/kustomization.yaml`, so applying `base` alone keeps SQLite, and applying the overlay points
the Deployment at a `database-secret.yaml` you fill in yourself; it does not run PostgreSQL for
you. Terraform: set `database_url` (empty by default, which keeps SQLite) and, only if you share
the instance, `database_schema` (default `immich_memories`).

```ini
IMMICH_MEMORIES_DATABASE_URL=postgresql+psycopg://immich_memories:change-me@postgres:5432/immich_memories
```

Plain PostgreSQL 14+. No extensions, no `vchord`, no pgvector: every vector comparison in this app
is exact numpy over a small candidate set (one film, one story, a 14-day window), so there is no
extension to install and no extension to keep in step with an upstream image.

## 3. A separate database on your existing PostgreSQL instance

The same URL, pointed at a database on an instance you already run for something else (including
Immich's own PostgreSQL container, if you want to reuse it without touching Immich's schema):

```ini
IMMICH_MEMORIES_DATABASE_URL=postgresql+psycopg://immich_memories:change-me@database:5432/immich_memories
```

`database` is the service name in Immich's own compose file, so the host resolves when this app
runs in that file ([next to your Immich stack](../docker.md#next-to-your-immich-stack)). From
anywhere else, use the address that reaches your PostgreSQL.

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

```ini
IMMICH_MEMORIES_DATABASE_URL=postgresql+psycopg://immich_memories:change-me@database:5432/immich
IMMICH_MEMORIES_DATABASE_SCHEMA=immich_memories
```

`IMMICH_MEMORIES_DATABASE_SCHEMA` is not in the shipped compose file: add it to the service's
`environment:` block next to the URL.

Create the role and schema while connected to Immich's database (`immich`), with no grants on
anything Immich owns:

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
