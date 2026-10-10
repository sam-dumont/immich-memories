---
title: Quick start
description: Install Basic, GPU or Full with Docker Compose, connect Immich and make your first film.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';
import InstallationFiles from '@site/src/components/InstallationFiles';

# Quick start

Run Immich Memories beside your existing Immich server. Choose your tier below, start the app,
then make a short film from one album.

| Tier | What you get | What you need |
|---|---|---|
| **Basic** | A complete film with titles and bundled music, up to 1080p | 2 CPU cores, 4 GiB RAM for the app |
| **GPU** | Basic plus picture descriptions and extra selection and sharing checks | NVIDIA GPU, driver and Container Toolkit; room for the app and model services |
| **Full** | GPU plus a text reader that refines the draft and writes titles | The GPU setup and a reader server with 32k context |

All three need Docker Compose v2, an Immich v2 or v3 library and an API key. Allow at least
25 GB for app data, plus images, model-service caches and finished films. GPU and Full give the
app an 8 GiB limit; model services need memory too. Check the [tier requirements](../run/requirements.md)
if you are choosing hardware.

**Other platforms:** [Synology, Unraid, TrueNAS and Portainer](../run/nas.md),
[native Mac or Linux](../run/uv-pip.md), [Kubernetes](../run/kubernetes.md).
Apple Silicon uses the native install for GPU and Full. For a NAS with a separate GPU machine,
use the [setup builder](/setup) and its GPU box option.

## 1. Download the files {#1-download-the-files}

Choose the tab for your tier. Run its commands in a new folder, separate from your Immich install.
The files match the release shown on this docs site.

<Tabs groupId="install-tier" defaultValue="basic">
<TabItem value="basic" label="Basic">

<InstallationFiles tier="basic" />

This starts one app container. No GPU or separate model server is needed.

</TabItem>
<TabItem value="gpu" label="GPU">

<InstallationFiles tier="gpu" />

This starts the app, CUDA inference and a caption server. The caption weights download on first
start. The commands select the NVIDIA override in `.env` for you.

</TabItem>
<TabItem value="full" label="Full">

<InstallationFiles tier="full" />

This starts the GPU services and selects Full. In `.env`, also set your reader connection:

```ini
READER_ENABLED=true
READER_URL=http://192.168.1.50:8000/v1
READER_MODEL=your-server-model-name
READER_API_KEY=
```

Use the exact model name served by your reader. Fill in its API key if it requires one.
The reader needs a 32k context window. [Set up a reader](../better/reader.md) if you do not have
one yet. It receives annotation text, including people and place names; choose a local server
if that text should stay on your network.

</TabItem>
</Tabs>

Prefer filled-in files or a stack editor? Use the [setup builder](/setup).

## 2. Connect Immich {#2-connect-immich}

In Immich, open **Account Settings → API Keys → New API Key**. Select the
[ten read permissions](../run/docker.md#the-api-key); leave **All** unchecked.
Open `.env` and fill in:

```ini
IMMICH_URL=http://192.168.1.10:2283
IMMICH_API_KEY=your-api-key-here
TZ=Etc/UTC
```

Use an Immich address the container can reach. `localhost` means the container itself.
Set `TZ` to your timezone. Upload permissions can wait until you want to send films back.

Create the output folder and a key for credentials saved in Settings:

```bash
mkdir -p output
sudo chown 1000:1000 output
printf 'IMMICH_MEMORIES_SECRET_KEY=%s\n' "$(openssl rand -hex 32)" >> .env
chmod 600 .env
```

Keep `.env` with your backups. On Synology, use the
[folder permission recipe](../run/nas.md#the-output-folder) in place of `chown`.

### If the app runs on a server or NAS

For access from another computer on your trusted LAN, also set these in `.env` **before starting**:

```ini
IMMICH_MEMORIES_AUTH_USERNAME=admin
IMMICH_MEMORIES_AUTH_PASSWORD=replace-with-your-own-long-password
UI_BIND_ADDRESS=0.0.0.0
```

Choose your own password of at least 12 characters. This route uses HTTP on your LAN.
For encrypted access, use an [SSH tunnel](../run/docker.md#reaching-the-ui-from-another-machine)
or an [HTTPS reverse proxy](../run/authentication.mdx#behind-a-reverse-proxy-with-tls).
On your own desktop, keep the default localhost binding.

## 3. Start and download the local models {#3-start-and-download-the-local-models}

```bash
docker compose up -d
docker compose exec -T immich-memories immich-memories models fetch
docker compose exec -T immich-memories immich-memories preflight
```

The first start pulls the images; `models fetch` downloads the models required by your tier.
Wait for both to finish. Later starts reuse those files.

Continue when the Immich connection, required models and output checks pass. GPU also needs
working inference, captions and Laya; Full adds the reader check. Follow the fix printed beside
any failed check. Software encoding is valid on Basic, and missing upload permissions do not
prevent a local film. [Read preflight results](../reference/installation-help.md#read-preflight).

## 4. Open the app {#4-open-the-app}

- **On this computer:** open [http://localhost:8080](http://localhost:8080).
- **On your server:** open `http://your-server-address:8080` and sign in with the login you set above.

Make [your first film](./first-film.mdx): choose an album of 20–50 pictures, review the cut,
then render. The same walkthrough works on Basic, GPU and Full.

## If it stops {#if-it-stops}

[Installation help](../reference/installation-help.md) covers connection errors, missing models,
ports, permissions and Docker networking. [Tested deployments](../run/tested-deployments.md)
records which versions and platforms have been exercised.
