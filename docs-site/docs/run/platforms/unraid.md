---
title: Unraid
---

import ComposePort from '@site/src/components/ComposePort';
import InstallationFiles from '@site/src/components/InstallationFiles';

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';
import StackAccess from './_stack-access.mdx';

# Unraid

Use the native Docker template for the Basic setup, or the Compose Manager alternative below. The app needs its own 4 GiB memory budget alongside Immich. These steps follow the Compose Manager documentation; a recorded installation on Unraid is still pending.

This platform route has not been tested end to end. See [tested deployments](../tested-deployments.md) for coverage.

## Native Docker template

The XML template uses the Community Applications format; it is not yet listed in the Community Applications catalog.

In Unraid's **Terminal** in the browser, install the unconfigured template:

<InstallationFiles kind="unraid" />

Open **Docker → Add Container**, select **immich-memories** from **Template**, and fill in the required Immich URL and API key. The template defaults to `latest`. To pin the app release shown in [Quick start](../../get-started/quick-start.md), set **Repository** to `ghcr.io/sam-dumont/immich-memories:X.Y.Z`, replacing `X.Y.Z` with that version (no `v` prefix).

Choose persistent host directories for configuration/models and finished films. They must be writable by UID/GID 1000; allow at least 25 GB for state plus films. Do not change permissions on an entire existing share. Set **Settings encryption key** to a random secret of at least 32 characters if you want to save credentials in Settings, and retain it across upgrades.

Keep **Network Type: Bridge** and the existing **Extra Parameters**. Its <code>--publish=127.0.0.1:<ComposePort />:8080/tcp</code> mapping is deliberately private. There is no separate port entry. For direct LAN access, set **both UI username and UI password**, then change it to <code>--publish=0.0.0.0:<ComposePort />:8080/tcp</code>. Choose another host port if <ComposePort /> is taken. Host networking bypasses it. The Unraid admin login does not protect the app.

Set film language after startup in [Settings](../../get-started/after-install.md).

Click **Apply**, then continue at [Open the app and download models](#3-prepare-and-check). A configured template contains your API key: do not share it.

## Compose Manager alternative

## 1. Open Compose Manager

Enable Docker in Unraid and install [Docker Compose Manager from Community Applications](https://ca.unraid.net/apps/docker-compose-manager-0mgvgou04hjv2a). Open its stack manager and add a stack named `immich-memories`. Compose Manager versions differ: the [maintainer's guide](https://github.com/mstrhakr/compose_plugin/blob/main/docs/getting-started.md) documents **Docker → Compose → Add Stack** for that fork.

## 2. Paste and start

Choose Basic, GPU or Full and enter your connection details below. GPU/Full need an NVIDIA host with the Container Toolkit or a separate GPU box; Full also needs a reader. Copy the generated `docker-compose.yml` into the stack's Compose editor and replace `replace-with-your-immich-api-key` with your [scoped Immich key](../docker.md#the-api-key). For Full, replace the reader-key placeholder too, or empty it if that server does not require one. Configure access below, then save and use the manager's **Compose Up** action. This file needs no separate `.env`.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

For GPU/Full on this NVIDIA host, select **Use NVIDIA CUDA containers**. For a separate worker,
fill in **GPU box address** and start the provided worker files on that machine first.

<StackAccess />

## 3. Open the app and download models {#3-prepare-and-check}

Open <code><ComposePort host="your-server-address" /></code> (use your chosen host port) and sign in with the app
username and password you just set. If you chose private localhost access, use its forwarded URL.

On **Memory**, click **Download models** and wait for it to finish. The card lists the files and
download hosts; it disappears when the required files are ready. If it is absent and no error is
shown, those files are already present. Downloads are kept on the config volume for later starts.

## 4. Check and make a film {#4-open-the-app}

**Basic:** continue to [your first film](../../get-started/first-film.mdx).

**GPU and Full:** the browser download does not check the external model services. On the **Docker** tab, click the `immich-memories` container icon and select **Console**. The template selects `sh`.
Run:

```bash
immich-memories preflight
```

This runs inside the app container, so do not add `docker exec`. Wait for inference and captions
(and the Full reader) to become ready, and resolve any required-service or storage errors before
making [your first film](../../get-started/first-film.mdx). Optional upload permissions can warn
while still allowing local films.

[Installation help](../../reference/installation-help.md) covers connection, port, permission and
startup errors. It also gives the CLI model-download command if you need it.
