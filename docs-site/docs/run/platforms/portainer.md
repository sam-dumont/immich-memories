---
title: Portainer
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Portainer

Use a **Docker Standalone** environment in Portainer. This recipe runs the app on that Docker host, which may be a different machine from the Portainer server. The interface steps follow [Portainer's stack documentation](https://docs.portainer.io/user/docker/stacks/add).

:::info Tested Docker Standalone path

A recent Portainer CE on Docker Standalone (Apple Silicon host) passes the Web editor stack
deployment, app readiness, and the browser Console commands below. This hasn't been checked
against a remote NAS tunnel or a published-release download; see the
[deployment matrix](../tested-deployments.md) for exact coverage.

:::

## 1. Create the stack

Open **Stacks → Add stack**, name it `immich-memories`, and select **Web editor**. Enter your Immich URL below, then copy the generated `docker-compose.yml` into the editor and replace `replace-with-your-immich-api-key` with your own [API key](../docker.md#the-api-key). The builder never asks for it. No `.env` upload is needed.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

## 2. Deploy

Click **Deploy the stack**. Wait for `immich-memories` to be running. If the host already uses port 8080, change the left-hand port in the mapping, keeping `127.0.0.1`.

`title_screens.locale: auto` follows the host's `LANG`, but the container sets none, so a film
always renders in English until you set `title_screens.locale: fr` (or add `LANG: fr_FR.UTF-8`
to the stack's environment) for a French one.

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

From your computer, tunnel to the **Docker host**:

Use the **Private UI access** command generated above; it uses your selected UI port. Replace `your-ssh-user@your-host` with your NAS login and address.

Open the localhost URL shown by the builder and make [your first film](../../get-started/first-film.mdx). For direct LAN access, [enable authentication before changing the port binding](../docker.md#reaching-the-ui-from-another-machine). Portainer's own login does not protect the app's port.
