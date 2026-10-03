---
title: Quick start
description: Install Immich Memories with Docker Compose and make your first photo and video highlight film. Runs on a server or NAS; no GPU required.
---

# Quick start

Run Immich Memories beside your Immich server, then try a 30-second film from 20–50 photos/videos. No GPU or model server needed.

You need Docker with Compose v2, Immich v2 or v3, and two CPU cores, 4 GiB of RAM for this app in addition to Immich/host needs and 25 GB for its data, plus the image and finished films. [Full requirements](../run/requirements.md).

import InstallationFiles from '@site/src/components/InstallationFiles';

## 1. Download the files

<InstallationFiles />

Create `output` yourself so Docker does not make it as root. This is where local films land.

## 2. Connect Immich

Open `.env` in a text editor and set:

```bash
IMMICH_URL=http://192.168.1.10:2283
IMMICH_API_KEY=your-api-key-here
```

Use the address the container can reach, usually your server's LAN address. `localhost` inside the container points at the container itself.

In Immich, create the key under **Account Settings > API Keys > New API Key**. Select the
[ten read permissions](../run/docker.md#the-api-key). Add the five upload permissions only if
you want to send films back to Immich; leave **All** unchecked.

## 3. Start and download the local models

```bash
docker compose pull
docker compose up -d
docker compose exec immich-memories immich-memories models fetch
docker compose exec immich-memories immich-memories preflight
```

`models fetch` downloads the pinned local model and dictionary. Picture processing runs on your CPU.
Preflight must pass Immich, required-model and output checks. Basic skips unconfigured optional
services; a home-coordinate warning does not block an album film.

## 4. Open the app

On the machine running Docker, open [http://localhost:8080](http://localhost:8080).

For a headless NAS, run this on your desktop first, replacing the SSH account and server name:

```bash
ssh -L 8080:localhost:8080 you@your-nas
```

Then open the same localhost address on your desktop. The default port is available locally; [authentication](../run/authentication.mdx) covers remote access.

Follow [Your first film](./first-film.mdx): create an Immich album with **20–50 supported
photos/videos**, choose **Album**, and set the length to **0.5 minutes**. Review the cut and render
with upload off. Shortening a film alone does not reduce how many inputs need preparation.

Cold setup includes the image pull, model download, input preparation and render. Allow several
hours for a real month's first preparation on a NAS. Hardware, input count and cache state matter;
[the phase guide](./first-film.mdx#progress-and-recovery) explains what progress and completion look like.
[After install](./after-install.md) covers home, people and backups. Got your first film?
[Choose your setup](./choose-your-setup.md) explains what more you can get.

## If it stops

| Message or symptom | Fix |
|---|---|
| `Encoder: Pinned DINOv2 export missing` | Run `models fetch` from step 3. |
| Output directory is not writable | Set ownership with `sudo chown -R 1000:1000 output`. |
| `Immich: Connection failed` | Check the URL and key in `.env`, then run `docker compose up -d` again. |

Check the installation at any time:

```bash
docker compose exec immich-memories immich-memories preflight
```

For NAS-specific permissions and CPU settings: [On a NAS](../run/nas.md). Without Docker: [pip / uv](../run/uv-pip.md).
