---
title: Portainer
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Portainer

Use a **Docker Standalone** environment in Portainer. This recipe runs the app on that Docker host, which may be a different machine from the Portainer server. The interface steps follow [Portainer's stack documentation](https://docs.portainer.io/user/docker/stacks/add).

The Docker Standalone Web editor and Console route has been checked; see [tested deployments](../tested-deployments.md) for its scope.

## 1. Create the stack

Open **Stacks → Add stack**, name it `immich-memories`, and select **Web editor**. Enter your Immich URL below, then copy the generated `docker-compose.yml` into the editor and replace `replace-with-your-immich-api-key` with your own [API key](../docker.md#the-api-key). The builder never asks for it. No `.env` upload is needed.

GPU and Full need an NVIDIA host with the Container Toolkit, or a separate GPU box. Full also needs a reader.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

Before deploying, choose how you will open the app: configure
[app login for LAN access](../docker.md#stack-editor-lan-access), or keep localhost and use
**Private UI access with an SSH tunnel** in the builder. On this NVIDIA host, select **Use NVIDIA
CUDA containers** for GPU/Full; for a separate worker, fill in **GPU box address** and start the
provided worker files on that machine first.

## 2. Deploy

Click **Deploy the stack**. Wait for `immich-memories` to be running. If the host already uses port 8080, change the left-hand port in the mapping, keeping `127.0.0.1`.

Set film language after startup in [Settings](../../get-started/after-install.md).

## 3. Prepare and check

Open **Containers → immich-memories → Console**, connect with `/bin/sh`, then run:

```bash
immich-memories models fetch
immich-memories preflight
```

Fix any reported connection or storage errors before making a film. Model downloads run once; later starts reuse the config volume.

On Basic, software encoding and CPU titles are supported results. Unconfigured optional
services and home coordinates are skipped. Read the individual rows: a read-only Immich key
can warn about uploads while still allowing you to make and download a film.

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
