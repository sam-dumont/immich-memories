---
title: report
---

# report

`immich-memories report` prints a report of one run that you can paste into a GitHub issue. It runs
on your machine, makes no network request and sends nothing: you read it, then decide what to share.

```bash
immich-memories report                 # the latest run, as Markdown
immich-memories report <run-id>        # one run
immich-memories report --json          # the same, for tooling
immich-memories report --bundle report.zip   # the full report and its logs, as a ZIP
```

The report holds the run's settings as shape (keys, not values), its errors and warnings, the log,
and a table of where the time went, phase by phase. That table is the first thing to read when a cut
is slow: `immich-memories runs show` prints the same timings in full, per picture.

Before anything reaches the report, it removes credentials, the names of the people you know, albums
and places, GPS coordinates, IP addresses, hostnames, URLs and absolute paths. IDs become hashes
that only match inside that one report. Pictures are never included. Exactly what is removed, and
how: [Privacy](../../run/privacy.md#diagnostic-reports).

A run of `generate --ask` ([a film from a sentence](../free-text.md)) adds a free-text section: the translation trace,
the pool funnel and the engine's picks as hashed IDs. Names become roles ("the owner's son"), place
names become "area A", words read by OCR become "text-1", and a birth date the trace dated from
becomes `[private]`. Captions stay out unless you pass `--include-flagged-captions`.

When the film got it wrong, say so on the run, then paste the report:

```bash
immich-memories report <run-id> --wrong <asset-id> --wrong <asset-id> --missing "the farm gate"
```

Each photo marked wrong gets the step that let it into the pool and whether the engine picked it.
The missing words are checked against the run: did the reading keep them, were they offered or
picked as the subject, and does any caption in the pool say them. The marks stay on the run, so a
later `report` shows them too.

The web UI has the same report behind **Copy report** on a run's page. Every flag is in the
[CLI reference](../../reference/cli-reference.md#report).
