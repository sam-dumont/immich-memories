---
title: Prepare the library
sidebar_label: prepare
---

# Prepare the library

Read a period's pictures ahead of time so later films can reuse the results. `prepare` makes no cut and renders no film. You do not need it before an ordinary film: `generate` prepares the pictures it needs itself.

## Read a month or year

```bash
immich-memories prepare --year 2025 --month 6
immich-memories prepare --year 2025
```

In Docker, prefix commands with `docker compose exec immich-memories`. Run `immich-memories models fetch` once before the first preparation.

A whole year is useful overnight on a NAS. Scope can also be an explicit start/end or start/period, using the same date options as `generate`.

## Resume and reuse

Rerunning resumes missing work. Later cuts reuse compatible facts; a changed producer may need to refresh its own facts. Changing home coordinates or people roles does not invalidate picture facts.

Exit 0 means preparation completed for the scope. Exit 1 means some facts are missing; the output names the producer and the count. On a captioned setup, check the caption service before rerunning.

[Database and fact versions](../../run/database.md) explains refresh and migration contracts.

## Measure the cost

The output lists each producer's elapsed time and rate per picture, then projects the measured rate across a library size. This tells you whether CPU inference is the part worth moving to a [GPU service](../../better/inference.md).

## Optional text summaries

With Full selection configured and its caption and reader services ready:

```bash
immich-memories prepare --year 2025 --overviews
```

This banks episode/month summaries too. It is optional; a model cut can produce missing summaries itself. [What a model adds](../../how-it-chooses/what-a-model-adds.md).

## Other library tasks

- [People commands](./people.md): roles, relationships, exports and saved groups.
- [Discover special days](./discover-days.md): an anniversary catalogue.
- [Preflight](../../run/maintenance/health-logs-cache.md#preflight): check connections, models and rendering.

Every preparation flag: [CLI reference](../../reference/cli-reference.md#prepare).
