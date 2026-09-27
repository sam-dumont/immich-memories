---
date: 2026-09-27
status: superseded by docs/designs/2026-09-27-the-store.md
builds-on: docs/research/2026-08-31-triage-heads-architecture.md (EmbeddingStore protocol)
---

# The store: SQLite or PostgreSQL, no vector database

This page used to plan PostgreSQL with VectorChord as the only backend for
[#871](https://github.com/sam-dumont/immich-video-memory-generator/issues/871). The 2026-09-26
review replaced that plan. The contract now lives in
[the store design](../designs/2026-09-27-the-store.md); the evidence, with file:line, is in
[the issue's architecture review](https://github.com/sam-dumont/immich-video-memory-generator/issues/871#issuecomment-5848750474).
The VectorChord plan stays in
[Git history](https://github.com/sam-dumont/immich-video-memory-generator/blob/e0db6c00/docs/research/2026-09-01-annotation-store-design.md).

## What changed

- **Two backends, one repository.** SQLAlchemy 2 and one Alembic history run on SQLite (the
  default, `~/.immich-memories/store.db`) and on plain PostgreSQL 14+. PostgreSQL is the owner's
  preferred deployment; SQLite is fully supported, not a fallback.
- **VectorChord and pgvector are dropped.** No query compares vectors across the library: scene
  prints are compared inside one film (`own @ theirs`, 14-day window), hashes inside one story
  or burst, places by haversine radius. Vectors are `LargeBinary` with `encoder_key` and `dim`,
  compared in numpy. An ANN index comes only for a measured library-wide need, after trying
  Immich's duplicates and smart-search APIs.
- **No extensions** means the store can live in Immich's own PostgreSQL, in a schema of its own,
  without touching Immich's `vchord` upgrades.
- **Two lifetimes.** The store (versioned, backed up) holds human decisions, paid-for model
  answers, run history and UI-edited settings. The cache (disposable, rebuilt on a version
  mismatch) holds derived analysis, hashes, scene prints and geocoding.

## What still holds from the old plan

- Stabilize first; the store lands before beta and the announcement.
- Preserve content keys, `manual:` people IDs, aliases, confirmations and owner decisions
  exactly. Recomputation is never a side effect of migration.
- Import legacy files read-only, idempotently, with a verify step. No dual writes, no fallback
  writes after cutover.
- Backup and restore are drilled on both backends before cutover.
