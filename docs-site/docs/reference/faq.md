---
title: FAQ
---

# FAQ

If something is broken, start with [Troubleshooting](./troubleshooting.md).

## Before you install

**Does it change my Immich library?**

Only when you upload. Making a film reads your library. With delivery on (`--upload-to-immich`, `upload.enabled`, or the upload switch in the web UI), it:

- uploads the finished film;
- tags it `immich-memories/generated`, plus the release and the day that made it (`immich-memories/version/...`, `immich-memories/generated-on/...`);
- writes the film's title into its Immich description, with the story summary when the experimental `title_screens.llm_titles` is on;
- with `upload.film_tags: true`, tags it by memory type, year and story (`immich-memories/type/...`, `/year/...`, `/story/...`);
- creates the album you asked for and adds the film.

A re-render into the same album moves the app's older copy to Immich's trash, where you can still restore it. [What Immich sees](../run/privacy.md#what-immich-sees) lists every write.

**What leaves my network?**

By default, only requests to your Immich server and the model downloads during setup. Optional readers, caption servers, translated place names and map fly-overs can contact other services. The update check sends one anonymous request to GitHub, and only when you ask (`immich-memories version --check`, **Check for updates** in Settings) or turn on `updates.check_daily`. [Privacy](../run/privacy.md) lists every request and what it sends.

**Will it run on my NAS?**

Yes. The default install cuts films on a NAS CPU from dates, places, favourites, people and what small
local classifiers measure on each picture. A GPU makes it faster and adds captions; a text model can refine
the draft ([Choose your setup](../get-started/choose-your-setup.md)). Sizes and the Synology trap are on
[On a NAS](../run/nas.md) and [Requirements](../run/requirements.md).

**Do I need face recognition?**

No. Without a person, a period film covers everyone. Named faces make people films possible and keep close
family in the film ([Home and people](../get-started/who-is-who.md)).

**iPhone only?**

No: anything FFmpeg decodes works. Live Photos are tested on iPhones; Samsung and Pixel motion photos are untested.

## After the first film

**Why is this picture in (or not)?**

`immich-memories runs why <asset id>` says where the picture passed or was dropped, and why.
`immich-memories runs story` prints the whole cut in play order, each shot with its story and the
reason it is there. The rules are on [How it chooses](../how-it-chooses/overview.md).

**Can I pick pictures myself?**

Yes. Tick or untick pictures in the web UI's pool and select **Preview with these choices**, star them in Immich,
or pass `--include` / `--exclude`. A tick outranks the editor. See [Edit the cut](../how-it-chooses/overrule-it.md).

**Why is the first cut slow and the second fast?**

The first cut prepares picture facts and saves them. Later cuts over the same pictures reuse those
facts and only choose their shots. Rendering is a separate step: it downloads originals, processes the
selected media and encodes the film. A re-render of the same selection reuses the sources an earlier run
prepared. [`prepare`](../make/cli/prepare.md) does a period's preparation ahead of time, overnight if you like.

**How much disk?**

The default cache budgets are 10 GB of downloaded video (kept up to 7 days), 30 GB of Immich
previews, 10 GB of prepared sources that re-renders reuse and 5 GB of past cut attempts. A running
preparation keeps the previews it is using and can go over its budget. Models, the store, temporary
render files and finished films come on top. See
[storage and cache sizing](../run/maintenance/storage-backups.md#caches).

**Can it make films on its own?**

Yes. Scheduled films wait `advanced.automation.cooldown_hours` (24 hours by default) after the last one. A film you ask for by hand (`auto run --force`, `POST /api/trigger?force=true`, or **Run this suggestion** in the web UI) skips the cooldown and doesn't count toward it, so the next scheduled film still comes on time. Rotation rules apply to both. [Automatic films](../make/automate.md) covers setup.

**Several people on one Immich server?**

One instance serves one library: the web UI has one user and one primary Immich account, which films upload to.
Run one instance per library. A people film can still read a second account's pictures: add it under
`immich.accounts`, then pass `generate --accounts primary,partner`, set `automation.accounts` for the daily run,
or pick it under **Immich accounts to read** on the web UI's New memory page
([A second Immich account](../run/multi-account.mdx)).

**Is it stable?**

Install, read-only Immich access and rendering are. Selection keeps improving on real libraries, so watch a cut
before you show it at a family party. The project is built with AI on purpose, as an experiment in keeping a
complex codebase clean that way: [Why this exists](../welcome/about.mdx).
