---
title: After install
description: Prepare models, check the installation, set home and people, then make and back up a film.
---

# After install

The app is running and can reach Immich. Do these once before making a larger film.
The commands below use Docker Compose; on a native install, omit
`docker compose exec immich-memories`.

## 1. Fetch the models

```bash
docker compose exec immich-memories immich-memories models fetch
```

This downloads the models required by your configuration. Wait for it to finish. It does not
prepare the whole library; the first cut prepares the pictures in the period you choose.

## 2. Check the installation

```bash
docker compose exec immich-memories immich-memories preflight
docker compose exec immich-memories immich-memories capabilities
```

Resolve errors using the fix printed beside each check. Missing home coordinates are addressed
in the next step. Software encoding and simpler titles are expected on some NAS CPUs.
`capabilities` shows the resolved tier; it does not prove a film has rendered.

## 3. Set home

Set `trips.homebase_latitude` and `trips.homebase_longitude` in **Settings** using your home
coordinates in decimal degrees. Both are needed to distinguish travel from ordinary days at home.
If the fields are controlled by your deployment, use the source shown beside them;
[configuration sources](../run/config-file.md#where-a-setting-comes-from) explains the priority.

The coordinates do not enable online place lookup. That has a
[separate switch](../run/privacy.md#geocoding-and-maps).

## 4. Confirm people

Name important faces in Immich. In **Settings > People**, press **Rescan the library**, set the
roles, and confirm or reject suggested relationships. The scan reads metadata; its guesses alone
do not make someone close family. [Home and people](./who-is-who.md) explains what changes.

## 5. Make one month

Open [http://localhost:8080](http://localhost:8080). Choose **Monthly Highlights**, a year and a
month with a few busy days, favourites and videos. Press **Cut**, review the shots, then **Render**.
The [first-film walkthrough](./first-film.mdx) shows the review controls.

On a headless NAS, use the [Quick start's SSH tunnel](./quick-start.md#4-open-the-app).
Local Docker films go into `./output`. Watch the finished film before sharing it.

## 6. Keep a backup

```bash
docker compose exec immich-memories immich-memories store backup
docker compose cp immich-memories:/home/immich/.immich-memories/backups ./backups
```

Copy backups off the host. Keep each backup with its `.manifest.json`, your deployment config
and the saved-credential encryption key. Losing the key means re-entering saved credentials.
[Storage and backups](../run/maintenance/storage-backups.md) covers restore and PostgreSQL.

## 7. Add what you need

Got a film you like? Keep this setup. For captions, extra sharing checks or a model's edit pass,
[Choose your setup](./choose-your-setup.md) explains the benefit and cost of each tier.
