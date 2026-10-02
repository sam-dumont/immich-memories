---
title: TrueNAS
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# TrueNAS

Use the Docker-based Apps system in TrueNAS 24.10 or newer. Older Kubernetes-based SCALE installs need a different deployment. These steps follow [TrueNAS's custom app documentation](https://apps.truenas.com/managing-apps/installing-custom-apps/); a recorded installation on TrueNAS is still pending.

:::info Not yet tested on TrueNAS

We have not tested these steps on this platform. Local template, manifest and browser checks do not establish a tested installation. Please [share your results in #1801](https://github.com/sam-dumont/immich-video-memory-generator/issues/1801), including platform/app versions and whether preflight and the first film worked.

:::

## 1. Open the YAML installer

With an Apps storage pool configured, open **Apps → Discover → ⋮ → Install via YAML**. Choose a lowercase application name such as `immichmemories`.

## 2. Paste and save

Enter your connection details below, paste the generated `docker-compose.yml` into **Custom Config**, and click **Save**. There is no adjacent `.env` file in this editor. If adapting a downloaded Compose file instead, resolve **every** `${...}` expression before pasting, including image tags, paths and ports.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

The example uses Docker-managed volumes. For datasets you can snapshot and share directly, create dedicated datasets first and replace the corresponding volume mounts with their absolute `/mnt/...` paths. Give UID/GID 1000 access to those datasets; do not change permissions on an entire existing storage pool.

## 3. Prepare and check

Open **Apps → Installed**, select `immichmemories`, then in **Workloads** click the **Shell** icon for the running app container. Choose `/bin/sh` if prompted. This is the app shell, not **System → Shell**. Run:

```bash
immich-memories models fetch
immich-memories preflight
```

Do not add `docker exec` inside this shell. Fix reported connection or storage errors before making a film. No SSH is needed for preparation. The shell requires **Web Shell Access** and the apps write role (`APPS_WRITE`), or Full Admin; see [TrueNAS's Workloads controls](https://cdn.truenas.com/docs/scale/apps/appsscreens/#workloads-widget).

## 4. Open the app

With SSH enabled on TrueNAS, run this from your computer:

```bash
ssh -L 8080:localhost:8080 your-ssh-user@your-truenas-host
```

Open `http://localhost:8080` and make [your first film](../../get-started/first-film.mdx). For direct LAN access, [enable authentication before changing the port binding](../docker.md#reaching-the-ui-from-another-machine). The TrueNAS admin login does not protect the app's port.
