---
title: Unraid
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Unraid

Use the native Docker template for the Basic setup, or the Compose Manager alternative below. The app needs its own 4 GiB memory budget alongside Immich. These steps follow the Compose Manager documentation; a recorded installation on Unraid is still pending.

This platform route has not been tested end to end. See [tested deployments](../tested-deployments.md) for coverage.

## Native Docker template

[Download the Unraid XML template](https://raw.githubusercontent.com/sam-dumont/immich-memories/main/deploy/unraid/immich-memories.xml). This is a distributable Community Applications format template; it is not yet listed in the Community Applications catalog.

In Unraid's **Terminal** in the browser, install the unconfigured template:

```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl --fail --location https://raw.githubusercontent.com/sam-dumont/immich-memories/main/deploy/unraid/immich-memories.xml -o /boot/config/plugins/dockerMan/templates-user/my-immich-memories.xml
```

Open **Docker → Add Container**, select **immich-memories** from **Template**, and fill in the required Immich URL and API key. Choose the published image tag in **Repository** if pinning a release. The default image is `latest`, matching the standalone Compose file.

Choose persistent host directories for configuration/models and finished films. They must be writable by UID/GID 1000; allow at least 25 GB for state plus films. Do not change permissions on an entire existing share. Set **Settings encryption key** to a random secret of at least 32 characters if you want to save credentials in Settings, and retain it across upgrades.

Keep **Network Type: Bridge** and the existing **Extra Parameters**. Its `--publish=127.0.0.1:8080:8080/tcp` mapping is deliberately private. There is no separate port entry. For direct LAN access, set **both UI username and UI password** before changing this mapping. Host networking bypasses it. The Unraid admin login does not protect the app.

Set film language after startup in [Settings](../../get-started/after-install.md).

Click **Apply**, then use the container console instructions below to fetch models and check readiness. No SSH is needed for these steps. A configured template contains your API key: do not share it.

## Compose Manager alternative

## 1. Open Compose Manager

Enable Docker in Unraid and install [Docker Compose Manager from Community Applications](https://ca.unraid.net/apps/docker-compose-manager-0mgvgou04hjv2a). Open its stack manager and add a stack named `immich-memories`. Compose Manager versions differ: the [maintainer's guide](https://github.com/mstrhakr/compose_plugin/blob/main/docs/getting-started.md) documents **Docker → Compose → Add Stack** for that fork.

## 2. Paste and start

Choose Basic, GPU or Full and enter your connection details below. GPU/Full need an NVIDIA host with the Container Toolkit or a separate GPU box; Full also needs a reader. Copy the generated `docker-compose.yml` into the stack's Compose editor, configure access below, then save and use the manager's **Compose Up** action. This file needs no separate `.env`.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

Before deploying, choose how you will open the app: configure
[app login for LAN access](../docker.md#stack-editor-lan-access), or keep localhost and use
**Private UI access with an SSH tunnel** in the builder. On this NVIDIA host, select **Use NVIDIA
CUDA containers** for GPU/Full; for a separate worker, fill in **GPU box address** and start the
provided worker files on that machine first.

## 3. Prepare and check

On the **Docker** tab, click the `immich-memories` container icon and select **Console**. The template selects `sh`. Run these commands inside that console:

```bash
immich-memories models fetch
immich-memories preflight
```

These are container commands: do not add `docker exec`. Fix reported connection or storage errors before making a film. See [Unraid's container controls](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/).

## 4. Open the app

For Compose Manager access from another computer on your trusted LAN, configure
[app login in the stack file](../docker.md#stack-editor-lan-access) before deploying it.
Then open `http://your-server-address:8080` and sign in. The container manager's own login does
not protect the app's port.

For private access, keep the localhost binding and use the builder's **Private UI access with
an SSH tunnel** instructions. Tunnel to the host running Docker, which may differ from the
container manager's host. Use your selected host port in either route.

Make [your first film](../../get-started/first-film.mdx).
[Installation help](../../reference/installation-help.md) covers port, permission and startup errors.
