---
title: Synology DSM
description: Create a Container Manager project, choose a tier and make a film.
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Synology DSM

Use **Container Manager → Project** on a DSM model that supports Container Manager.
Basic runs on the NAS. For GPU or Full, use a separate NVIDIA machine and enter its private
address in **GPU box address** below. Full also needs a reader.
[Requirements](../requirements.md) covers memory and storage.

The SSH/Compose route has completed a first film; the GUI Project wizard has not been exercised.
See [tested deployments](../tested-deployments.md) for exact coverage.

## 1. Create a project

Create a dedicated project folder in File Station. In **Container Manager → Project → Create**,
name the project `immich-memories`, select that folder and choose the Compose editor.

Choose your tier below. Enter the Immich URL the NAS can reach, copy `docker-compose.yml` into
the editor, and replace `replace-with-your-immich-api-key` with your
[Immich API key](../docker.md#the-api-key). For Full, also replace the reader key placeholder,
or empty it for a reader without authentication.

<SetupBuilder initialPlatform="synology" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

Keep the saved file private using **File Station → Properties → Permission**. It contains keys.

## 2. Choose access and start {#2-start-the-project}

To open the app directly from another computer on your trusted LAN, follow
[app login for a stack editor](../docker.md#stack-editor-lan-access) before deploying.
Keep the default localhost mapping if you prefer the **Private UI access** SSH tunnel above.

Finish the wizard and start the project. No Web Station portal is needed.
For a separate GPU machine, run the generated GPU-host commands there first; keep its model
service port accessible only from your app host on your private network.

## 3. Prepare and check

Open a `/bin/sh` terminal in the running app container:

```bash
immich-memories models fetch
immich-memories preflight
```

Wait for downloads and your model services, then resolve any failed required check.
The default Basic setup supports software encoding and CPU titles.

## 4. Open the app

For LAN access, open `http://your-nas-address:8080` and sign in. For a tunnel, use the localhost
URL printed by the builder. Then make [your first film](../../get-started/first-film.mdx).
DSM's own login does not protect the app's port.

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
