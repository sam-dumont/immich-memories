---
title: Portainer
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Portainer

Use a **Docker Standalone** environment in Portainer. This recipe runs the app on that Docker host, which may be a different machine from the Portainer server. The interface steps follow [Portainer's stack documentation](https://docs.portainer.io/user/docker/stacks/add).

:::info Not yet tested on Portainer

We have not tested these installation steps on a real Portainer setup. The generated files and documentation form have local checks, but that does not validate this platform's installation.

We welcome people to try it and [share their results in #1805](https://github.com/sam-dumont/immich-video-memory-generator/issues/1805). Please include your platform version, app version, selected tier, and whether preflight and the first film worked. Successful runs are useful too.

:::

## 1. Create the stack

Open **Stacks → Add stack**, name it `immich-memories`, and select **Web editor**. Enter your connection details below, then copy the generated `docker-compose.yml` into the editor. No `.env` upload is needed.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

## 2. Deploy

Click **Deploy the stack**. Wait for `immich-memories` to be running. If the host already uses port 8080, change the left-hand port in the mapping, keeping `127.0.0.1`.

## 3. Prepare and check

Open **Containers → immich-memories → Console**, connect with `/bin/sh`, then run:

```bash
immich-memories models fetch
immich-memories preflight
```

Fix any reported connection or storage errors before making a film. Model downloads run once; later starts reuse the config volume.

## 4. Open the app

From your computer, tunnel to the **Docker host**:

Use the **Private UI access** command generated above; it uses your selected UI port. Replace `your-ssh-user@your-host` with your NAS login and address.

Open the localhost URL shown by the builder and make [your first film](../../get-started/first-film.mdx). For direct LAN access, [enable authentication before changing the port binding](../docker.md#reaching-the-ui-from-another-machine). Portainer's own login does not protect the app's port.
