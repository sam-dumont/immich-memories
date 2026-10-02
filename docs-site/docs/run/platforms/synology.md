---
title: Synology DSM
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Synology DSM

Use **Container Manager → Project** on a DSM model that supports Container Manager. Start with the NAS setup; it needs no separate GPU or model server. The project steps follow [Synology's documentation](https://kb.synology.com/en-global/DSM/help/ContainerManager/docker_project?version=7).

:::info New Container Manager recipe

This new generated Container Manager setup has not yet been rerun from scratch on Synology. Earlier Synology installation, preflight and rendering checks are recorded in the [measured results](../../better/measured.md#tested-setups).

We welcome people to try it and [share their results in #1805](https://github.com/sam-dumont/immich-video-memory-generator/issues/1805). Please include your platform version, app version, selected tier, and whether preflight and the first film worked. Successful runs are useful too.

:::

## 1. Create a project

Create a folder for the project in File Station. In Container Manager, open **Project → Create**, name it `immich-memories`, select that folder, and choose the option to create the Compose file in the editor. Enter your connection details below and paste the generated `docker-compose.yml` into the editor:

<SetupBuilder initialPlatform="synology" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

## 2. Start the project

Finish the project wizard and start it. No Web Station portal is needed for the SSH tunnel below. The file deliberately has no `cpus:` quota: some DSM kernels reject it before the container starts. See [Synology CPU limits](../nas.md#do-not-use-cpus-on-a-synology) if you want to reserve cores for other apps.

## 3. Prepare and check

Open a `/bin/sh` terminal in the running `immich-memories` container and run:

```bash
immich-memories models fetch
immich-memories preflight
```

Alternatively, [enable SSH in DSM](https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/system_terminal?version=7) and run `sudo docker exec immich-memories immich-memories models fetch`, followed by the same command ending in `preflight`. Fix connection or storage errors before making a film.

## 4. Open the app

With SSH enabled on DSM, run this from your computer:

```bash
ssh -L 8080:localhost:8080 your-dsm-user@your-nas
```

Open `http://localhost:8080` and make [your first film](../../get-started/first-film.mdx). DSM's login does not protect a separately published app port. For direct LAN access, [turn on app authentication first](../docker.md#reaching-the-ui-from-another-machine).
