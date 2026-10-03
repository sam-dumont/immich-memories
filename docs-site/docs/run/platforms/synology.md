---
title: Synology DSM
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Synology DSM

Use **Container Manager → Project** on a DSM model that supports Container Manager. Start with the Basic setup; it needs no separate GPU or model server. The project steps follow [Synology's documentation](https://kb.synology.com/en-global/DSM/help/ContainerManager/docker_project?version=7).

:::info Tested on Synology; GUI project wizard not yet exercised

The exact generated NAS file passed a fresh-volume SSH/Compose installation on DSM 7.3: explicit model download, preflight, a default first film, playback, and a Settings URL save/reload/restore. The Container Manager **Project wizard** itself was not exercised. See the [cold-install measurement](../../better/measured.md#generated-cold-installs) and earlier [Synology checks](../../better/measured.md#tested-setups).

We welcome people to try it and [share their results in #1805](https://github.com/sam-dumont/immich-video-memory-generator/issues/1805). Please include your platform version, app version, selected tier, and whether preflight and the first film worked. Successful runs are useful too.

:::

## 1. Create a project

Create a folder for the project in File Station. In Container Manager, open **Project → Create**, name it `immich-memories`, select that folder, and choose the option to create the Compose file in the editor. Enter your connection details below and paste the generated `docker-compose.yml` into the editor:

<SetupBuilder initialPlatform="synology" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

The saved Compose file contains your Immich API key and Settings encryption key. Restrict the project folder and file to your DSM user in **File Station → Properties → Permission**, including inherited entries. For an SSH-created project, set and check the file modes after saving:

```bash
chmod 700 /volume1/homes/your-user/immich-memories
chmod 600 /volume1/homes/your-user/immich-memories/docker-compose.yml
stat -c '%a %n' /volume1/homes/your-user/immich-memories /volume1/homes/your-user/immich-memories/docker-compose.yml
```

Use your actual project path. Our DSM test created a file with mode `777` despite `umask 077`; explicit `chmod` produced `700` for the folder and `600` for the file. Check the DSM permissions too: these mode numbers alone do not prove that an additional ACL grants nobody access.

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

Your SSH account must also be allowed to forward TCP connections. Enabling SSH in DSM does not guarantee this: our DSM 7.3 test account connected but the tunnel failed with `administratively prohibited`. Its server policy had `AllowTcpForwarding no`, with exceptions for two administrator accounts. Ask your NAS administrator for an approved forwarding-enabled account; do not change the NAS's SSH policy just to follow this guide.

Use the **Private UI access** command generated above; it uses your selected UI port. Replace `your-ssh-user@your-host` with your NAS login and address.

If forwarding is unavailable, use the existing [authenticated HTTPS reverse-proxy recipe](../network-security.md#https-reverse-proxy). Enable app authentication first and proxy to the generated localhost port. This is a separate access setup; DSM's login alone does not authenticate the app.

Open the localhost URL shown by the builder and make [your first film](../../get-started/first-film.mdx). DSM's login does not protect a separately published app port. For direct LAN access, [turn on app authentication first](../docker.md#reaching-the-ui-from-another-machine).
