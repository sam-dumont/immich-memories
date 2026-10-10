---
title: Portainer
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';
import StackAccess from './_stack-access.mdx';

# Portainer

Use a **Docker Standalone** environment in Portainer. This recipe runs the app on that Docker host, which may be a different machine from the Portainer server. The interface steps follow [Portainer's stack documentation](https://docs.portainer.io/user/docker/stacks/add).

The Docker Standalone Web editor and Console route has been checked; see [tested deployments](../tested-deployments.md) for its scope.

## 1. Create the stack

Open **Stacks → Add stack**, name it `immich-memories`, and select **Web editor**. Enter your Immich URL below, then copy the generated `docker-compose.yml` into the editor and replace `replace-with-your-immich-api-key` with your own [API key](../docker.md#the-api-key). The builder never asks for it. No `.env` upload is needed.

GPU and Full need an NVIDIA host with the Container Toolkit, or a separate GPU box. Full also needs a reader. Replace the generated reader-key placeholder with its API key, or empty it if that server does not require one.

<SetupBuilder initialPlatform="linux" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

For GPU/Full on this NVIDIA host, select **Use NVIDIA CUDA containers**. For a separate worker,
fill in **GPU box address** and start the provided worker files on that machine first.

<StackAccess />

## 2. Deploy

Click **Deploy the stack**. Wait for `immich-memories` to be running.

Set film language after startup in [Settings](../../get-started/after-install.md).

## 3. Open the app and download models {#3-prepare-and-check}

Open `http://your-server-address:8080` (use your chosen host port) and sign in with the app
username and password you just set. If you chose private localhost access, use its forwarded URL.

On **Memory**, click **Download models** and wait for it to finish. The card lists the files and
download hosts; it disappears when the required files are ready. If it is absent and no error is
shown, those files are already present. Downloads are kept on the config volume for later starts.

## 4. Check and make a film {#4-open-the-app}

**Basic:** continue to [your first film](../../get-started/first-film.mdx).

**GPU and Full:** the browser download does not check the external model services. Open **Containers → immich-memories → Console** and connect with `/bin/sh`.
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
