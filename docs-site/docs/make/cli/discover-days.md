---
title: Discover special days
---

# Discover special days

Build a catalogue of occasions from your library. The app can then offer them on anniversaries or let you choose them as a **Special day** film.

## Build the catalogue

```bash
immich-memories discover-days --since 2015
```

In Docker, prefix commands with `docker compose exec immich-memories` (the export/import recipe below shows the paths separately).

Choose the first year you want scanned. `--until` defaults to the current year. It works on a plain NAS from library facts; Full selection can check proposed occasions using its text reader.

A scan resumes by default, skipping years already catalogued. It can take time across a large library. Set [People and home](../../get-started/who-is-who.md) first so the scan can distinguish family activity and time away.

## See what is due

```bash
immich-memories days-due
immich-memories days-due --on 2026-12-24
```

This lists anniversaries within three days. The UI's **Special day** picker also lists the catalogue, and accepts any date even without a catalogue entry.

## Refresh an older year

To re-scan and replace that year's catalogue entries:

```bash
immich-memories discover-days --replace --since 2024 --until 2024
```

This can remove old entries. Export the catalogue first if you want a copy of what it held.

## Edit the catalogue

```bash
immich-memories days-export --to days.json
```

Edit the exported JSON, then import it:

```bash
immich-memories days-import --from days.json
```

Import replaces the catalogue with the edited list. Use this for a missed day or a wrong title.

For Docker, export onto the host, edit `./output/days.json`, then import its container path:

```bash
docker compose exec -T immich-memories immich-memories days-export > ./output/days.json
docker compose exec immich-memories immich-memories days-import --from /app/output/days.json
```

`--to days.json` would write inside the container. The shipped output mount makes the edited
host file available at `/app/output/days.json`.

[Special-day discovery rules](../../reference/special-days.md) covers windows, evidence, reader confirmation and repetition checks. [CLI reference](../../reference/cli-reference.md#discover-days) lists the options.
