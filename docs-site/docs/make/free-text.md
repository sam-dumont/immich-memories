---
title: A film from a sentence
description: Preview a sentence-based film before committing to its experimental selection.
---

# A film from a sentence

Type something like "at the park with kids" or "our cat through the years" and the app tries to turn it into a film.

:::caution Highly experimental
This was tuned on one real library and tried on a handful of test households. It can and will
get your request wrong on yours. Preview the scope and the pictures before trusting the result.
:::

## Before you try it

You need the **Full** tier: GPU picture preparation, a caption service and a configured [text reader](../better/reader.md). Run `immich-memories models fetch` to install the pinned WordNet dictionary.

A text reader by itself on the Basic tier is enough for titles, but not for this feature.

## It prepares the period it asks about

A caption-only subject ("our cat", "my knitting") reads captions, and a library nobody has run
`prepare` on has none yet. Rather than answer "not possible" on pictures nobody has looked at, a
request checks its own period first: the dates it parsed, or the whole library for "along the
years". A person film or a computed selection (a trip, someone's first or last picture) reads
faces and GPS, never a caption, so it is never affected by this.

Preview first, on the CLI or in the web UI: a preview only checks and warns, it never
prepares anything. **Make the film** stays on even when the window needs preparing; that
button is what pays the cost.

```bash
immich-memories generate --ask "our cat along the years" --dry-run
```

```
1,234 pictures in this period aren't prepared yet; preparing them first takes about 8 min
```

Making the film says the same thing, then prepares:

```bash
immich-memories generate --ask "our cat along the years" --no-render
```

```
1,234 pictures in this period aren't prepared yet; preparing them first takes about 8 min
Preparing 1,234 pictures over 1 window
...
```

A second request over the same period prepares nothing new: the captions are already banked,
the same way `immich-memories prepare` banks them. It still checks the window first, though,
which on a large library can itself take a couple of minutes (Immich's own search, not a
model). The web client shows the same warning in its preview, before it starts.

## Preview, then make the film

In the web UI, use **Describe the film you want** on **Memory** and inspect the preview. Read
the translated people, dates, places and subject. Check the pool: a plausible sentence does not
guarantee the right pictures. The preview's verdict is one of four: **possible** (enough
pictures, the film is made), **thin** (fewer, a short film is made and the run says why),
**not possible** (the pool is empty) or **needs preparation** (the window above). When it looks right:

```bash
immich-memories generate --ask "our cat along the years" --no-render
```

This saves an actual cut for review. Render it from **Runs**, or use [`runs render`](./cli/runs.md#runs-render).

## How it works

The sentence becomes filters over facts and captions already prepared from your library. Those filters build a pool; the normal editor chooses shots from it. An empty pool makes no film.

The pool only holds pictures the run's accounts can see. In a [household setup](../run/multi-account.mdx), a plain ask reads your primary account only. Add `--accounts primary,partner`, or select both accounts in the web UI, to search both libraries.

The title comes from a model that reads your request as the occasion, written in the film's
configured language ([titles and languages](../reference/output-rendering.md#languages)); that
is not necessarily the language you typed the sentence in, and it is never the raw sentence
itself. With no model, or one that refuses, the title falls back to the dated template.

## Leaving things out

"No", "without" and their equivalent in your language exclude rather than require: "landscapes, no humans" drops any picture with a face or a person in its caption, "sans les enfants" drops children without requiring them. A named person works the same way: "without Alex" drops Alex's own pictures. Mix a request freely: "with the kids, no rain" keeps the kids filter and drops nothing about rain, since each clause of your sentence is read on its own.

"Only" narrows a company word to the kind you named: "only the performers" keeps musicians, singers, dancers and the rest of that cast, and drops the audience. The exclusion travels with the film all the way to the final cut, so a picture that slipped past the pool filter still gets caught and reported.

The sentence supplies the scope, so do not combine `--ask` with `--year`, `--person` or an album scope. For a predictable date or person film, use [the normal film chooser](./memory-types.mdx).

## When a result is bad

Wrong-picture and missing-subject feedback is CLI-only: `immich-memories report RUN_ID --wrong ASSET_ID --missing "the red bike"`. [Create a report](./cli/report.md) and read its preview before sharing it. Reports do not include pictures; flagged captions are opt-in.

The [sentence parser reference](../reference/sentence-parser.md) has the translation trace, voting, WordNet matching, pool rules and known limits. [Privacy](../run/privacy.md) lists what the caption service and reader receive.
