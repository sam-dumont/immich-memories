---
title: Migrating older installs
---

# Migrating older installs

Use this when upgrading an install from before the store or the current command set. For the
normal upgrade procedure, see [Upgrading](../maintenance/upgrading.md).

## Config compatibility

There is no automatic config migration. An unknown key inside a known section is ignored, so a
renamed field stops doing anything; an unknown top-level key or an invalid value fails at
startup. When a setting seems to have stopped working, look for its rename in the release notes.

Keys of the retired per-clip scorer (`content_analysis`, `audio_content`, `transcription`,
`analysis.max_refinement_passes`, `analysis.scene_threshold` and the other pacing dials,
`photos.max_ratio`, `photos.read_moments`, `hardware.gpu_analysis` and their family) load with one
warning listing each one. Delete them to silence it; nothing reads them. The same goes for the
`scheduler:` section (its command is gone, see below), `cache.max_age_days`,
`title_screens.show_decorative_lines`, `triage.enabled` and `triage.bundle`: nothing read the last
four. Head weights of your own go in `editorial.preparation.head_bundle`.

## Removed commands

These commands went in the release that closed
[#973](https://github.com/sam-dumont/immich-video-memory-generator/issues/973). A script that still
calls one fails with `No such command`.

| Removed | Use instead |
|---------|-------------|
| `scheduler list/status/start` | `auto run` on a timer for the daily candidate ([Automation](../../make/automate.md)). For a fixed film on a fixed date, a cron job or Kubernetes CronJob that runs `generate` ([below](#a-fixed-film-on-a-fixed-date)) |
| `analyze` | `prepare`. `analyze` only counted a year's videos; `years` lists the years |
| `export-project` | Nothing. It wrote a JSON list of videos that nothing read back |
| `cache stats`, `cache export`, `cache import` | `store status` for row counts, `store backup` / `store restore` to move data. They only read the retired scorer's asset scores, which nothing writes any more |
| `cache backup` | `store backup`. It copied `cache.db`, which holds only a cache now |

### A fixed film on a fixed date

The old `scheduler:` block filled the date in for you (January fires a year in review of the year
before). A cron line does it with `date`:

```bash
# 15 January, 09:00: last year's review, uploaded to an album
0 9 15 1 * immich-memories generate --memory-type year_in_review --year $(( $(date +\%Y) - 1 )) --upload-to-immich --album "Memories"
```

## Data compatibility

The store migrates forward when it opens, so an upgrade never loses run history or banked facts.

**The first start after the store arrived** imports what the install kept in files: `people.yaml`,
`special-days.json`, the run history, automation attempts, notification health and asset scores in
`cache.db`, the run index, `annotations.sqlite` (owner decisions included), `judgments.db`, the `structure-banks/` audience
and vote banks, and the owner edits saved beside reviewed films. It
happens once, the first time a process opens a store that has no import record while those files
exist, and the log says what it brought in:

```text
Importing the legacy files under /home/immich/.immich-memories into sqlite:////home/immich/.immich-memories/store.db (once)
  /home/immich/.immich-memories/people.yaml: 14 imported, 0 already there
  ...
```

- The files are read, never changed or deleted.
- Two processes starting at the same moment (the UI and a scheduled run, say) queue on a lock; the
  second finds the first one's record and skips.
- Every later start costs one read of that record.
- A failed import is logged and retried at the next start. `immich-memories store import --verify`
  runs it by hand and checks every record ([the store commands](../database.md#managing-the-store)).
- `IMMICH_MEMORIES_IMPORT_FROM` (or `database.import_from` in `config.yaml`) points it at another
  directory, for a container that mounts an old data volume somewhere other than `~/.immich-memories`.

`cache.db` itself stays where it is: the import reads it and never writes it, and nothing else
opens it any more. Once `store import --verify` passes you can delete it. The video cache is safe to delete at any time; it costs a re-download. Finished MP4s depend
on nothing.

## Upgrading Immich from v2 to v3

Both majors work ([Immich API compatibility](../config-file.md#immich-api-compatibility)). Leave
this alone through the server upgrade:

```yaml
immich:
  api_version: auto  # auto | v2 | v3
```

On the next start, `auto` detects the server major and uses its API contract. Explicit `v2`
and `v3` are manual troubleshooting escape hatches for unusual proxies or deployments that prevent
correct detection; they force the selected contract. They are not an upgrade step.

The client handles the three v3 wire changes that affect generation:

- **Duration:** v2 duration strings and v3 integer milliseconds are normalized to seconds.
- **Upload:** v2 keeps the device identity fields; v3 sends `filename` and omits the removed
  `deviceAssetId` and `deviceId` fields. v3 assets report no device, so a re-render recognises its
  earlier upload by the `immich-memories/generated` tag on both versions. The tag goes on once
  Immich has finished reading the file, because Immich's own metadata read rewrites an asset's tags.
- **Search dates:** date bounds include a UTC offset, which v3 requires.

After upgrading Immich:

```bash
immich-memories config test
```

This is a read-only authentication and compatibility check. It does not search assets, generate a
video, create an album, or upload anything. It prints the `v2` or `v3` contract it resolved.

## End of API compatibility notes
