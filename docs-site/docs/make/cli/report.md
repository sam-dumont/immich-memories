---
title: report
---

# report

Create a redacted report of one run for a GitHub issue. This command sends nothing; review the report before sharing it.

```bash
immich-memories report
immich-memories report RUN_ID
immich-memories report RUN_ID --bundle report.zip
```

Without an ID it uses the latest run. A supplied `RUN_ID` must be the full ID; unlike `runs` commands, `report` does not resolve prefixes. The ZIP includes the report and full redacted logs. `--json` gives the report as data.

## What it includes

Errors, warnings, logs and a table of time and memory by phase. When the film is slow, start with that table.

The report removes credentials, names, places, coordinates, network addresses and absolute paths. Asset IDs become report-local hashes. Pictures are never included. [Exact redaction rules](../../run/privacy.md#diagnostic-reports).

Sentence requests also include a redacted interpretation trace. Captions stay out unless you pass `--include-flagged-captions`. Review those captions before sharing.

## Mark a wrong result

For a sentence request, persist wrong-picture IDs and missing words on the run:

```bash
immich-memories report RUN_ID --wrong ASSET_ID --missing "the red bike"
```

The report then shows the filter that admitted the picture and checks how the missing words were interpreted. Later reports retain these marks.

In the web UI, open a run and use **Copy report** or **Download report**. Every flag: [CLI reference](../../reference/cli-reference.md#report).
