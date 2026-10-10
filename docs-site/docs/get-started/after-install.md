---
title: After install
description: Set home and people, choose film language, keep backups and schedule films.
---

# After install

Once you have made [your first film](./first-film.mdx), configure the parts you want to use
regularly. These steps apply to every tier.

## Set home and people {#3-set-home}

In **Settings**, set your home coordinates for trips and local holidays. Name important people
in Immich, then use **Settings → People → Rescan the library** and confirm relationships.
[Home and people](./who-is-who.md) explains the choices. An album film works without them.

<span id="4-confirm-people" />

## Choose film language

Set `title_screens.locale` in Settings to the language you want, for example `fr`.
`auto` follows the process language; a stock container renders English. The interface and the
film have separate language settings. [Titles and music](../make/titles-maps-music.md) covers format.

## Make a larger film {#5-make-one-month}

Try **Monthly Highlights** for a month with pictures you like, or choose a trip, a birthday or a
year. A larger period needs more preparation. Compatible picture facts from earlier films are
reused. Review the cut and finished film before sharing.

## Save credentials in Settings

The Immich URL and API key in `.env` work without further setup. To save credentials through
Settings instead, [set an encryption key](../run/config-file.md#secrets-in-the-database) and
[remove the corresponding environment values](../run/config-file.md#where-a-setting-comes-from).
Environment values take precedence over Settings.

## Keep a backup {#6-keep-a-backup}

With Docker Compose, run from your installation folder:

```bash
docker compose exec immich-memories immich-memories store backup
docker compose cp immich-memories:/home/immich/.immich-memories/backups ./backups
```

On a native install, run `immich-memories store backup`; it prints the backup path.
Copy backups off the host. Keep each backup with its `.manifest.json`, your deployment config
and the encryption key if you save credentials in Settings. Losing that key means re-entering
those credentials.
[Storage and backups](../run/maintenance/storage-backups.md) covers restore and PostgreSQL.


## Upload or schedule films

To send films back to Immich, add the [upload permissions](../run/docker.md#the-api-key) and select
**Upload the film to Immich** when rendering. A successful upload removes the local copy.
[Automatic films](../make/automate.md) covers daily selection, scheduling and delivery.

## Change the tier or services {#7-add-what-you-need}

[Choose your setup](./choose-your-setup.md) explains Basic, GPU and Full. Follow its
[tier-change steps](./choose-your-setup.md#change-services-later) to download any missing models and check the new configuration. Compatible facts and review
decisions stay in your store.

<span id="1-fetch-the-models" /><span id="2-check-the-installation" />

Still completing installation? Use [Quick start](./quick-start.md) or
[Installation help](../reference/installation-help.md).
