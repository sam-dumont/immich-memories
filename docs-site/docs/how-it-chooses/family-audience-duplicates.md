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

These checks can miss things or flag an innocent picture. **Look through the cut before sharing it.** On a NAS, the app has fewer ways to identify private activities: Just us and Family use the same conservative rules. GPU and Full add descriptions and the local Laya text classifier's activity check. [Useful words](./glossary.md) explains the tiers and readers.

## Fix a picture’s decision

The pool tells you when a picture is held and why.

- **Clear hold** lets you approve that picture for Just us, Family or Anyone. The decision lasts across future cuts.
- **Never use** keeps it out of future automatic selections.
- **Undo** removes your decision so the app’s holds apply again.

These decisions are different from editing one finished cut. Ticking or unticking in its pool changes that cut’s saved revision; it does not clear a hold for future films. [Review and adjust](./overrule-it.md) shows the workflow.

## Family and repeats

Confirm the relationships that apply to your household in [Home and people](../get-started/who-is-who.md). The editor can give a close relative an appearance when they are present in the period but missing from the cut.

Copies and bursts normally become one shot. Later checks remove repeated scenes, favouring your stars and useful motion. A shorter film is preferable to the same sunset twice.

For detector coverage, hold precedence, family-seat thresholds and duplicate comparisons, read the [sharing and duplicate reference](../reference/selection-internals/family-audience-duplicates.md).
