---
title: TrueNAS
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# TrueNAS

Use the Docker-based Apps system in TrueNAS 24.10 or newer. Older Kubernetes-based SCALE installs need a different deployment. These steps follow [TrueNAS's custom app documentation](https://apps.truenas.com/managing-apps/installing-custom-apps/); a recorded installation on TrueNAS is still pending.

This platform route has not been tested end to end. See [tested deployments](../tested-deployments.md) for coverage.

## 1. Open the YAML installer

With an Apps storage pool configured, open **Apps → Discover → ⋮ → Install via YAML**. Choose a lowercase application name such as `immichmemories`.

## 2. Paste and save

Enter your Immich URL below, paste the generated `docker-compose.yml` into **Custom Config**, replace `replace-with-your-immich-api-key` with your own [API key](../docker.md#the-api-key) (the builder never asks for it), then configure access below before clicking **Save**. There is no adjacent `.env` file in this editor. If adapting a downloaded Compose file instead, resolve **every** `${...}` expression before pasting, including image tags, paths and ports.

GPU and Full need an NVIDIA host with the Container Toolkit, or a separate GPU box. Full also needs a reader.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

Before deploying, choose how you will open the app: configure
[app login for LAN access](../docker.md#stack-editor-lan-access), or keep localhost and use
**Private UI access with an SSH tunnel** in the builder. On this NVIDIA host, select **Use NVIDIA
CUDA containers** for GPU/Full; for a separate worker, fill in **GPU box address** and start the
provided worker files on that machine first.

The example uses Docker-managed volumes. For datasets you can snapshot and share directly, create dedicated datasets first and replace the corresponding volume mounts with their absolute `/mnt/...` paths. Give UID/GID 1000 access to those datasets; do not change permissions on an entire existing storage pool.

Set film language after startup in [Settings](../../get-started/after-install.md).

## 3. Prepare and check

Open **Apps → Installed**, select `immichmemories`, then in **Workloads** click the **Shell** icon for the running app container. Choose `/bin/sh` if prompted. This is the app shell, not **System → Shell**. Run:

```bash
immich-memories models fetch
immich-memories preflight
```

Do not add `docker exec` inside this shell. Fix reported connection or storage errors before making a film. No SSH is needed for preparation. The shell requires **Web Shell Access** and the apps write role (`APPS_WRITE`), or Full Admin; see [TrueNAS's Workloads controls](https://cdn.truenas.com/docs/scale/apps/appsscreens/#workloads-widget).

## 4. Open the app

For direct access from another computer on your trusted LAN, configure
[app login in the stack file](../docker.md#stack-editor-lan-access) before deploying it.
Then open `http://your-server-address:8080` and sign in. The container manager's own login does
not protect the app's port.

For private access, keep the localhost binding and use the builder's **Private UI access with
an SSH tunnel** instructions. Tunnel to the host running Docker, which may differ from the
container manager's host. Use your selected host port in either route.

Make [your first film](../../get-started/first-film.mdx).
[Installation help](../../reference/installation-help.md) covers port, permission and startup errors.
