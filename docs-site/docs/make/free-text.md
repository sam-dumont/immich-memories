---
title: A film from a sentence
description: Preview a sentence-based film before committing to its experimental selection.
---

# A film from a sentence

Type something like "at the park with kids" or "our cat through the years" and the app tries to turn it into a film.

:::caution Experimental
The translation can get your request wrong. Preview the scope and the pictures before trusting the result.
:::

## Before you try it

You need the **Full** tier: GPU picture preparation, a caption service and a configured [text reader](../better/reader.md). Run `immich-memories models fetch` to install the pinned WordNet dictionary.

A text reader by itself on the Basic tier is enough for titles, but not for this feature.

## It prepares the period it asks about

A request reads captions, and a library nobody has run `prepare` on has none yet. Rather than
answer "not possible" on pictures nobody has looked at, a request checks its own period first
and, if any of it is missing, prepares it before answering: a warning with the count and an
estimate, then the usual preparation lines, then the answer.

```
1,240 pictures in this period aren't prepared yet; preparing them first takes about 6 min
Preparing 1,240 pictures over 1 window
...
```

A second request over the same period pays nothing: the captions it prepared are banked, the
same way `immich-memories prepare` banks them. For a whole library's worth of years, expect the
preparation itself to take minutes, not seconds; the web client shows the same warning before
it starts.

## Preview first

In the web UI, use **Describe the film you want** on **Memory** and inspect the preview. On the CLI:

```bash
immich-memories generate --ask "at the park with kids" --dry-run
```

Read the translated people, dates, places and subject. Check the pool: a plausible sentence does not guarantee the right pictures. When it looks right:

```bash
immich-memories generate --ask "at the park with kids" --no-render
```

This saves an actual cut for review. Render it from **Runs**, or use [`runs render`](./cli/runs.md#runs-render).

## How it works

The sentence becomes filters over facts and captions already prepared from your library. Those filters build a pool; the normal editor chooses shots from it. An empty pool makes no film.

The sentence supplies the scope, so do not combine `--ask` with `--year`, `--person` or an album scope. For a predictable date or person film, use [the normal film chooser](./memory-types.mdx).

## When a result is bad

Wrong-picture and missing-subject feedback is CLI-only: `immich-memories report RUN_ID --wrong ASSET_ID --missing "the red bike"`. [Create a report](./cli/report.md) and read its preview before sharing it. Reports do not include pictures; flagged captions are opt-in.

The [sentence parser reference](../reference/sentence-parser.md) has the translation trace, voting, WordNet matching, pool rules and known limits. [Privacy](../run/privacy.md) lists what the caption service and reader receive.
