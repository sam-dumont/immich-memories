---
title: TrueNAS
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';
import StackAccess from './_stack-access.mdx';

# TrueNAS

Use the Docker-based Apps system in TrueNAS 24.10 or newer. Older Kubernetes-based SCALE installs need a different deployment. These steps follow [TrueNAS's custom app documentation](https://apps.truenas.com/managing-apps/installing-custom-apps/); a recorded installation on TrueNAS is still pending.

This platform route has not been tested end to end. See [tested deployments](../tested-deployments.md) for coverage.

## 1. Open the YAML installer

With an Apps storage pool configured, open **Apps → Discover → ⋮ → Install via YAML**. Choose a lowercase application name such as `immichmemories`.

## 2. Paste and save

Enter your Immich URL below, paste the generated `docker-compose.yml` into **Custom Config**, replace `replace-with-your-immich-api-key` with your own [API key](../docker.md#the-api-key) (the builder never asks for it), then configure access below before clicking **Save**. There is no adjacent `.env` file in this editor. If adapting a downloaded Compose file instead, resolve **every** `${...}` expression before pasting, including image tags, paths and ports.

GPU and Full need an NVIDIA host with the Container Toolkit, or a separate GPU box. Full also needs a reader. Replace the generated reader-key placeholder with its API key, or empty it if that server does not require one.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

For GPU/Full on this NVIDIA host, select **Use NVIDIA CUDA containers**. For a separate worker,
fill in **GPU box address** and start the provided worker files on that machine first.

<StackAccess />

The example uses Docker-managed volumes. For datasets you can snapshot and share directly, create dedicated datasets first and replace the corresponding volume mounts with their absolute `/mnt/...` paths. Give UID/GID 1000 access to those datasets; do not change permissions on an entire existing storage pool.

Set film language after startup in [Settings](../../get-started/after-install.md).

## 3. Open the app and download models {#3-prepare-and-check}

Open `http://your-server-address:8080` (use your chosen host port) and sign in with the app
username and password you just set. If you chose private localhost access, use its forwarded URL.

On **Memory**, click **Download models** and wait for it to finish. The card lists the files and
download hosts; it disappears when the required files are ready. If it is absent and no error is
shown, those files are already present. Downloads are kept on the config volume for later starts.

## 4. Check and make a film {#4-open-the-app}

**Basic:** continue to [your first film](../../get-started/first-film.mdx).

**GPU and Full:** the browser download does not check the external model services. Open **Apps → Installed**, select `immichmemories`, then in **Workloads** click the **Shell** icon for the running app container. Choose `/bin/sh` if prompted. This is the app shell, not **System → Shell**.
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

The container shell requires **Web Shell Access** and the apps write role (`APPS_WRITE`), or Full Admin; see [TrueNAS's Workloads controls](https://cdn.truenas.com/docs/scale/apps/appsscreens/#workloads-widget).
