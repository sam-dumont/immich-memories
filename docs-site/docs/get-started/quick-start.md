---
title: Quick start
---

# Quick start

Run Immich Memories beside your Immich server, then make a film from one month. No GPU or model server needed.

You need Docker with Compose v2, Immich v2 or v3, and two CPU cores, 4 GB of RAM and 25 GB of disk for this container. [Full requirements](../run/requirements.md).

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

In Immich, create the key under **Account Settings > API Keys > New API Key**. **All** permissions work; the [minimal permissions](../run/docker.md#the-api-key) are listed in the Docker guide.

## 3. Start and download the local models

```bash
docker compose up -d
docker compose exec immich-memories immich-memories models fetch
```

The second command downloads the local model and dictionary once. Picture processing runs on your CPU.

## 4. Open the app

On the machine running Docker, open [http://localhost:8080](http://localhost:8080).

For a headless NAS, run this on your desktop first, replacing the SSH account and server name:

```bash
ssh -L 8080:localhost:8080 you@your-nas
```

Then open the same localhost address on your desktop. The default port is available locally; [authentication](../run/authentication.mdx) covers remote access.

Choose **Monthly Highlights**, a year and a month with photos or videos. Press **Cut**, review the result, then **Render**. The first cut reads the month's pictures; later cuts reuse that work.

[Your first film](./first-film.mdx) shows the review and editing steps.

## If it stops

| Message or symptom | Fix |
|---|---|
| Missing pinned model | Run `models fetch` from step 3. |
| Output directory is not writable | Set ownership with `sudo chown -R 1000:1000 output`. |
| Cannot connect to Immich | Check the URL and key in `.env`, then run `docker compose up -d` again. |

Check the installation at any time:

```bash
docker compose exec immich-memories immich-memories preflight
```

For NAS-specific permissions and CPU settings: [On a NAS](../run/nas.md). Without Docker: [pip / uv](../run/uv-pip.md).
