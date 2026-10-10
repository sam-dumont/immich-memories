---
title: Synology DSM
description: Create a Container Manager project, choose a tier and make a film.
---

import ComposePort from '@site/src/components/ComposePort';

import SetupBuilder from '@site/src/components/SetupBuilder';
import {Screenshot} from '@site/src/components/ThemedScreenshot';
import StackStorage from './_stack-storage.mdx';
import StackAccess from './_stack-access.mdx';

# Synology DSM

Use **Container Manager → Project** on a DSM model that supports Container Manager.
Basic runs on the NAS. For GPU or Full, use a separate NVIDIA machine and enter its private
address in **GPU box address** below. Full also needs a reader. If those services already run
in Kubernetes or on another host, use the [existing-service settings](../nas.md#existing-model-services).
[Requirements](../requirements.md) covers memory and storage.

The project and folder dialogs below were checked in DSM. The SSH/Compose route has completed
a first film; an end-to-end GUI deployment has not. See
[tested deployments](../tested-deployments.md) for exact coverage.

## 1. Create a project

1. Open **Container Manager → Project → Create** and name the project `immich-memories`.
2. Click **Set Path**, select your `docker` shared folder, then **Create Folder**. Name the
   folder `immich-memories`, click **OK**, select the new folder and click **Select**.

   <Screenshot src="/img/platforms/synology-create-folder.jpg" alt="Create Folder dialog with immich-memories as the folder name" />

3. Set **Source** to **Create docker-compose.yml**. This opens the editor.

   <Screenshot src="/img/platforms/synology-create-project.jpg" alt="Create Project dialog with the project name, Set Path button and Create docker-compose.yml source selected" />

Tap either screenshot to read it at full size.

Choose your tier below. Enter the Immich URL the NAS can reach, copy `docker-compose.yml` into
the editor, and replace `replace-with-your-immich-api-key` with your
[Immich API key](../docker.md#the-api-key). For Full, also replace the reader key placeholder,
or empty it for a reader without authentication.

<SetupBuilder initialPlatform="synology" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

Keep the saved file private using **File Station → Properties → Permission**. It contains keys.

## 2. Choose access and start {#2-start-the-project}

<StackAccess />

Finish the wizard and start the project. No Web Station portal is needed.
For a new separate GPU worker, run the generated GPU-host commands there first; keep its model
service port accessible only from your app host on your private network. Skip those commands
when reusing existing services.

## 3. Open the app and download models {#3-prepare-and-check}

Open <code><ComposePort host="your-nas-address" /></code> (use your chosen host port) and sign in with the app
username and password you just set. If you chose private localhost access, use its forwarded URL.

On **Memory**, click **Download models** and wait for it to finish. The card lists the files and
download hosts; it disappears when the required files are ready. If it is absent and no error is
shown, those files are already present. Downloads are kept on the config volume for later starts.

## 4. Check and make a film {#4-open-the-app}

**Basic:** continue to [your first film](../../get-started/first-film.mdx).

**GPU and Full:** the browser download does not check the external model services. In Container Manager, open a `/bin/sh` terminal in the running `immich-memories` container.
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

## Other access routes and troubleshooting

[Synology access and troubleshooting](../reference/synology-operations.md) covers an HTTPS
reverse proxy, forwarding restrictions and a release-file installation over SSH.
[Installation help](../../reference/installation-help.md) covers readiness errors.

<span id="sshcompose-installation-from-published-files" />
<span id="authenticated-proxy" />
<span id="lan-port-with-app-login-no-tunnel-no-proxy" />
<span id="checking-auth-with-curl" />

[HTTPS proxy](../reference/synology-operations.md#authenticated-proxy) ·
[LAN login](../docker.md#stack-editor-lan-access) ·
[SSH/Compose](../reference/synology-operations.md#sshcompose-installation-from-published-files)
