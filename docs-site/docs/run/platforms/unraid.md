---
title: Unraid
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Unraid

Use the native Docker template for the NAS setup, or the Compose Manager alternative below. The app needs its own 4 GiB memory budget alongside Immich. These steps follow the Compose Manager documentation; a recorded installation on Unraid is still pending.

:::info Not yet tested on Unraid

We have not tested these steps on this platform. Local template, manifest and browser checks do not establish a tested installation. Please [share your results in #1801](https://github.com/sam-dumont/immich-video-memory-generator/issues/1801), including platform/app versions and whether preflight and the first film worked.

:::

## Native Docker template

[Download the Unraid XML template](https://raw.githubusercontent.com/sam-dumont/immich-video-memory-generator/main/deploy/unraid/immich-memories.xml). This is a distributable Community Applications format template; it is not yet listed in the Community Applications catalog.

In Unraid's **Terminal** in the browser, install the unconfigured template:

```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl --fail --location https://raw.githubusercontent.com/sam-dumont/immich-video-memory-generator/main/deploy/unraid/immich-memories.xml -o /boot/config/plugins/dockerMan/templates-user/my-immich-memories.xml
```

Open **Docker → Add Container**, select **immich-memories** from **Template**, and fill in the required Immich URL and API key. Choose the published image tag in **Repository** if pinning a release. The default image is `latest`, matching the standalone Compose file.

Choose persistent host directories for configuration/models and finished films. They must be writable by UID/GID 1000; allow at least 25 GB for state plus films. Do not change permissions on an entire existing share. Set **Settings encryption key** to a random secret of at least 32 characters if you want to save credentials in Settings, and retain it across upgrades.

Keep **Network Type: Bridge** and the existing **Extra Parameters**. Its `--publish=127.0.0.1:8080:8080/tcp` mapping is deliberately private. There is no separate port entry. For direct LAN access, set **both UI username and UI password** before changing this mapping. Host networking bypasses it. The Unraid admin login does not protect the app.

Click **Apply**, then use the container console instructions below to fetch models and check readiness. No SSH is needed for these steps. A configured template contains your API key: do not share it.

## Compose Manager alternative

## 1. Open Compose Manager

Enable Docker in Unraid and install [Docker Compose Manager from Community Applications](https://ca.unraid.net/apps/docker-compose-manager-0mgvgou04hjv2a). Open its stack manager and add a stack named `immich-memories`. Compose Manager versions differ: the [maintainer's guide](https://github.com/mstrhakr/compose_plugin/blob/main/docs/getting-started.md) documents **Docker → Compose → Add Stack** for that fork.

## 2. Paste and start

Enter your connection details below. Copy the generated `docker-compose.yml` into the stack's Compose editor, save, and use the manager's **Compose Up** action. This file needs no separate `.env`.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

## 3. Prepare and check

On the **Docker** tab, click the `immich-memories` container icon and select **Console**. The template selects `sh`. Run these commands inside that console:

```bash
immich-memories models fetch
immich-memories preflight
```

These are container commands: do not add `docker exec`. Fix reported connection or storage errors before making a film. See [Unraid's container controls](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/).

## 4. Open the app

From your computer, tunnel to the Unraid host:

```bash
ssh -L 8080:localhost:8080 your-ssh-user@your-unraid-host
```

Open `http://localhost:8080` and make [your first film](../../get-started/first-film.mdx). For direct LAN access, [enable authentication before changing the port binding](../docker.md#reaching-the-ui-from-another-machine). If 8080 is occupied, change the host port in both the Compose mapping and the tunnel destination.
