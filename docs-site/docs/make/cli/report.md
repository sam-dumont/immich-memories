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

The web UI has the same report behind **Copy report** on a run's page. Every flag is in the
[CLI reference](../../reference/cli-reference.md#report).
