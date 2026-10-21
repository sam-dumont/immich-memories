---
title: Who may see your film
---

# Who may see your film

Choose **Who may see it** in the brief. The default shown in the brief is **As configured**: Family unless `defaults.sharing` says otherwise.

| Level | Intended viewers | What changes |
|---|---|---|
| **Just us** | Your household | Captioned private household moments, such as bath time, may stay in. |
| **Family** | The wider circle you share personal films with | Those private activities stay out when the app recognises them. |
| **Shareable** | Anyone | Only pictures that pass the stricter sharing checks stay in. |

```bash
immich-memories generate --year 2024 --month 6 --sharing family
```

These checks can miss things or flag an innocent picture. **Look through the cut before sharing it.** On Basic, the app has fewer ways to identify private activities: Just us and Family use the same conservative rules. GPU and Full add descriptions and the local Laya text classifier's activity check. [Useful words](./glossary.md) explains the tiers and readers.

<Diagram name="decide-keep-drop" headline="Favourites help pictures stay. Source, sharing and repeated-scene checks still apply." />
## Fix a picture’s decision

The pool tells you when a picture is held and why.

- **Clear hold** lets you approve that picture for Just us, Family or Anyone. The decision lasts across future cuts.
- **Never use** keeps it out of future automatic selections.
- **Undo** removes your decision so the app’s holds apply again.

These decisions are different from editing one finished cut. Ticking or unticking in its pool changes that cut’s saved revision; it does not clear a hold for future films. [Review and adjust](./overrule-it.md) shows the workflow.

## Family and repeats

Confirm the relationships that apply to your household in [Home and people](../get-started/who-is-who.md). The editor can give a close relative an appearance when they are present in the period but missing from the cut.

Copies and bursts normally become one shot. When Immich holds the same picture more than once, the film plays one file:

- **A copy or an edit.** A shared album's smaller copy, or the edited version your phone uploaded next to the original (same file name, same camera, same capture instant): the newest full-size version plays, so your edit wins over the original and a downscaled album copy never does. A star, the people Immich recognised and a `generate --include` or `--exclude` on any of the files count for the one kept.
- **The same bytes twice.** Your partner's phone uploaded it too, or a second account holds it: one copy plays, and a star on any of them counts.
- **An Immich stack.** The stack's top picture plays. A star, the people Immich recognised and a `generate --include` or `--exclude` on any picture in the stack count for it. Reading stacks needs the optional `stack.read` permission on the [API key](../run/docker.md#the-api-key); without it every stacked picture is its own candidate.

Later checks remove repeated scenes, favouring your stars and useful motion. A shorter film is preferable to the same sunset twice.

A photo with no camera behind it (forwarded through a chat app, saved from a website) stays out by default. When a film has a gap with no camera picture at all, a week, a month, a year or an earlier birthday, you can let those copies fill it: set `advanced.analysis.forwarded_copies_when_short: true`. They pass the same checks as camera pictures, collages stay out, and a copy of a picture your library already holds is dropped. A copy is dated when you received it, so an old photo shared again can land in the wrong year.

A video with no camera behind it and a file name no camera writes (an app's edited export, say a
lap-timing video with a speedometer drawn over it) is only a suspect, because a phone clip
somebody renamed looks the same. It plays last in its moment, holds for a beat instead of the
12 seconds real footage can grow to, never opens the film, and gives its place to any other
footage of the moment. Star it and it plays like any other clip.

For detector coverage, hold precedence, family-seat thresholds and duplicate comparisons, read the [sharing and duplicate reference](../reference/selection-internals/family-audience-duplicates.md).
