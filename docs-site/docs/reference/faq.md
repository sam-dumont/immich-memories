---
title: FAQ
---

# FAQ

If something is broken, start with [Troubleshooting](./troubleshooting.md).

## Before you install

**Does it change my Immich library?**

Ordinary selection reads your library. When delivery is enabled (`--upload-to-immich`, `upload.enabled`, or the web UI's upload switch), it uploads the finished film, creates the `immich-memories/generated` tag if needed and tags the asset. It can also create the requested album and add the film to it. A re-render into the same album moves the app's superseded copy to Immich's trash; it does not hard-delete it. [What Immich sees](../run/privacy.md#what-immich-sees) lists these writes.

**What leaves my network?**

Library processing talks to your Immich server. Model setup downloads weights from their distribution hosts. Optional readers, caption servers, translated place names and map fly-overs can contact other services; [Privacy](../run/privacy.md) lists the requests and what they send.

**Will it run on my NAS?**

Yes, it works on a plain NAS: the default install cuts films on a NAS CPU from dates, places, favourites,
people and what small local classifiers measure on each picture. A GPU makes it faster and adds captions,
and a text model can refine the draft
([What a GPU or a model adds](../get-started/what-a-gpu-or-a-model-adds.md)). Sizes and the one Synology trap are on
[On a NAS](../run/nas.md) and [Requirements](../run/requirements.md).

**Do I need face recognition?**

No. Without a person, a period covers everyone. Named faces make people films possible and let it keep close
family in the film ([Home and people](../get-started/who-is-who.md)).

**iPhone only?**

Anything FFmpeg decodes. Live Photos are tested on iPhones; Samsung and Pixel motion photos are untested.

## After the first film

**Why is this picture in (or not)?**

`immich-memories runs why <asset id>` says where it passed or was dropped and why. The rules are on
[How it chooses](../how-it-chooses/overview.md).

**Can I pick pictures myself?**

Yes. Tick or untick in the web UI’s pool and select **Preview with these choices**, star it in Immich, or pass `--include` / `--exclude`.
A tick outranks the editor. See [Edit the cut](../how-it-chooses/overrule-it.md).

**Why is the first cut slow and the second fast?**

The first cut measures each picture it can reach once and banks the result; the second is mostly the render.
`prepare` does a period ahead of time, overnight if you like.

**How much disk?**

Caches are capped by config: 10 GB of downloaded video (kept 7 days), 10 GB of Immich previews, plus the
store (`store.db`). Films come on top, sized by length, resolution and codec.

**Can it make films on its own?**

Yes, one a day by default (`automation.cooldown_hours` controls the gap): [Automate it](../make/automate.md).

**Several people on one Immich server?**

The web UI is single-user, single-replica: one primary Immich account (the upload target). Run one instance per library.
People whose pictures use separate accounts can still get one people film from both: add the second account under
`immich.accounts` and run `generate --accounts primary,partner` on the CLI
([A second Immich account](../run/multi-account.mdx)); `automation.accounts` does the same for the daily
run, and **Immich accounts to read** on the web UI's New memory page for a film made there.

**Is it stable?**

Install, read-only Immich access and rendering are. Selection keeps improving, measured on real libraries, so
review a cut before you show it at a family party. The project is built with AI on purpose, as an experiment in
keeping a complex codebase clean that way: [Why this exists](../welcome/about.mdx).
