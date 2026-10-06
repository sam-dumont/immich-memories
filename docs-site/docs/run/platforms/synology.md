---
title: Synology DSM
---

import SetupBuilder from '@site/src/components/SetupBuilder';
import StackStorage from './_stack-storage.mdx';

# Synology DSM

Use **Container Manager → Project** on a DSM model that supports Container Manager. Start with the Basic setup; it needs no separate GPU or model server. The project steps follow [Synology's documentation](https://kb.synology.com/en-global/DSM/help/ContainerManager/docker_project?version=7).

:::info Tested route: SSH/Compose. GUI Project wizard not yet exercised

A fresh-volume SSH/Compose install passes end to end: model download, preflight, a default
first film, playback, and a Settings URL save/reload/restore. See the
[deployment matrix](../tested-deployments.md) for the exact release this covers. The Container
Manager **Project wizard** itself has not been exercised; if you try it, [report your
results](https://github.com/sam-dumont/immich-memories/issues), including your DSM version, app
version, selected tier, and whether preflight and the first film worked.

:::

## 1. Create a project

Create a folder for the project in File Station. In Container Manager, open **Project → Create**, name it `immich-memories`, select that folder, and choose the option to create the Compose file in the editor. Enter your Immich URL below, paste the generated `docker-compose.yml` into the editor, and replace `replace-with-your-immich-api-key` with your own [API key](../docker.md#the-api-key) (the builder never asks for it):

<SetupBuilder initialPlatform="synology" initialInline showPlatform={false} showCommands={false} />

<StackStorage />

Once you paste your key in, the saved Compose file contains your Immich API key and Settings encryption key. Restrict the project folder and file to your DSM user in **File Station → Properties → Permission**, including inherited entries. For an SSH-created project, set and check the file modes after saving:

```bash
chmod 700 /volume1/homes/your-user/immich-memories
chmod 600 /volume1/homes/your-user/immich-memories/docker-compose.yml
stat -c '%a %n' /volume1/homes/your-user/immich-memories /volume1/homes/your-user/immich-memories/docker-compose.yml
```

Use your actual project path. DSM can create this file with mode `777` despite `umask 077`; the
explicit `chmod` above produces `700` for the folder and `600` for the file. Check the DSM
permissions too: these mode numbers alone do not prove that an additional ACL grants nobody access.

## 2. Start the project

Finish the project wizard and start it. No Web Station portal is needed for the SSH tunnel below. The file deliberately has no `cpus:` quota: some DSM kernels reject it before the container starts. See [Synology CPU limits](../nas.md#do-not-use-cpus-on-a-synology) if you want to reserve cores for other apps.

## 3. Prepare and check

Open a `/bin/sh` terminal in the running `immich-memories` container and run:

```bash
immich-memories models fetch
immich-memories preflight
```

Alternatively, [enable SSH in DSM](https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/system_terminal?version=7) and run `docker exec immich-memories immich-memories models fetch` (add `sudo` if your user isn't in the `docker` group), followed by the same command ending in `preflight`. Fix connection or storage errors before making a film.

## 4. Open the app

Your SSH account must also be allowed to forward TCP connections. Enabling SSH in DSM does not
guarantee this: a non-admin account can connect over SSH while the tunnel still fails with
`administratively prohibited`, because DSM's default policy sets `AllowTcpForwarding no` except
for administrator accounts. Ask your NAS administrator for an approved forwarding-enabled account;
do not change the NAS's SSH policy just to follow this guide.

Use the **Private UI access** command generated above; it uses your selected UI port. Replace `your-ssh-user@your-host` with your NAS login and address.

If forwarding is unavailable, use [the authenticated proxy procedure below](#authenticated-proxy). DSM's login alone does not authenticate the app.

Open the localhost URL shown by the builder and make [your first film](../../get-started/first-film.mdx). DSM's login does not protect a separately published app port. For direct LAN access, [turn on app authentication first](../docker.md#reaching-the-ui-from-another-machine).

## SSH/Compose installation from published files

This is a separate route from the Project wizard. On the NAS, enable SSH for an approved
account and open a terminal in a new app-only directory under your DSM home. Follow
[Quick start, Download the files](../../get-started/quick-start.md#1-download-the-files) there,
using that documentation build's published assets. A preview without downloads cannot supply
this prebuilt route. Never use the Immich project's directory.

Edit `.env` on the NAS: set `IMMICH_URL`, `IMMICH_API_KEY`, `TZ`, and keep `TIER=basic` and
`UI_BIND_ADDRESS=127.0.0.1`. Use the [ten read permissions](../docker.md#the-api-key).
From the resulting `immich-memories` project directory on the NAS:

```bash
chmod 700 .
chmod 600 .env
mkdir -p output
/usr/syno/bin/synoacltool -addace output user:1000:allow:rwxpdDaARWc--:fd--
sudo docker compose -p immich-memories pull
sudo docker compose -p immich-memories up -d
sudo docker compose -p immich-memories exec immich-memories immich-memories models fetch
sudo docker compose -p immich-memories exec immich-memories immich-memories preflight
```

The `synoacltool` line gives the container's uid 1000 write access to `output` and keeps your own
entry; see [the output folder](../nas.md#the-output-folder) for why `chown` isn't enough.
`title_screens.locale: auto` follows the host's `LANG`, but the container sets none, so a film
always renders in English until you set `title_screens.locale: fr` (or add `LANG: fr_FR.UTF-8`
to `.env`) for a French one. Check DSM ACLs as described above. Run every later Compose command from this directory with
`-p immich-memories`; the explicit project name also determines its named volume prefix.
This stock release-file route uses host port **8080**. If occupied, change only the number before
`:8080` in the port line, so it reads `${UI_BIND_ADDRESS:-127.0.0.1}:18081:8080`, and use 18081 for
both tunnel and proxy upstream. Keep `${UI_BIND_ADDRESS:-127.0.0.1}`: the LAN route depends on it.

On your **desktop**, the permitted-tunnel route is:

```bash
ssh -o ExitOnForwardFailure=yes -L 8080:127.0.0.1:8080 your-user@your-nas
```

Keep that session open and visit `http://localhost:8080` on the desktop. A forwarding-denied
message when the browser connects requires the proxy route below, even if SSH itself logged in.

## Authenticated proxy when forwarding is disabled {#authenticated-proxy}

Use DSM's HTTPS reverse proxy on the NAS with **application Basic auth**. The app remains
published on `127.0.0.1:8080`; there is no unauthenticated LAN mapping in this procedure.
`memories.example.com` below is an example: substitute your LAN DNS name and its valid TLS
certificate, already configured on the NAS. This does not require internet exposure or router forwarding.

1. On the NAS, edit the project's `.env` and set both `IMMICH_MEMORIES_AUTH_USERNAME` and
   `IMMICH_MEMORIES_AUTH_PASSWORD` to your chosen login and a unique password of at least
   12 characters. Keep `UI_BIND_ADDRESS=127.0.0.1`.
2. In `docker-compose.yml`, under the app's `environment`, add
   `IMMICH_MEMORIES_AUTH__PUBLIC_URL: https://memories.example.com` and
   `IMMICH_MEMORIES_SERVER__SECURE_COOKIES: "true"`. Configure the exact proxy peer as
   `IMMICH_MEMORIES_AUTH__TRUSTED_PROXIES: '["YOUR_PROXY_PEER_IP"]'` using the
   [peer-address check](../network-security.md#https-reverse-proxy). Keep these edits in your
   deployment files; `.env` alone passes only variables the Compose file references.
3. Recreate the app on the **NAS**, before creating/enabling the proxy:

   ```bash
   sudo docker compose -p immich-memories up -d
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/v1/settings
   ```

   The protected settings endpoint must answer **401** without a session (and 200 after login).
   Stop if it returns settings. The public health endpoint is deliberately anonymous and is not an auth test.
4. In DSM **Control Panel → Login Portal → Advanced → Reverse Proxy**, create a source
   **HTTPS**, hostname `memories.example.com`, port **443**, and destination **HTTP**,
   hostname `127.0.0.1`, port **8080**. Assign the matching certificate in DSM's certificate
   settings. Preserve `Host`, set `X-Forwarded-Proto` to `https`, and overwrite forwarded
   client headers as in the [proxy checklist](../network-security.md#https-reverse-proxy).
   Menu labels depend on DSM; this GUI sequence still needs the validation below.
5. On a **second LAN machine**, open a private browser window at
   `https://memories.example.com`. Confirm it requires app login before showing settings or
   media. Sign in, then follow [the bounded trial](../../get-started/first-film.mdx).
6. Restart with `sudo docker compose -p immich-memories restart`, and repeat the signed-out,
   login and saved-run checks from the second machine.

| Symptom | Check |
|---|---|
| 502 or connection refused | Proxy destination is HTTP to the NAS loopback host port, not HTTPS or container port 80; check `sudo docker compose -p immich-memories ps` |
| Login works over HTTP but fails through HTTPS | Check public URL, secure cookies, actual trusted peer and forwarded protocol; use [the auth guide](../authentication.mdx) |
| Wrong password / temporary lockout | Use the app login from `.env`, not the DSM password; repeated failures trigger the documented rate limit |
| Output permission failure | Check this project's `output` owner and DSM ACLs, then rerun preflight; do not change Immich's media directories |

## LAN port with app login (no tunnel, no proxy)

If your account can't forward ports and you don't want to set up the proxy, publish the port on
the LAN with app authentication on. In `.env`, set `IMMICH_MEMORIES_AUTH_USERNAME`,
`IMMICH_MEMORIES_AUTH_PASSWORD` and `UI_BIND_ADDRESS=0.0.0.0`, then `docker compose up -d`.
From a second machine, `/api/v1/settings`, thumbnails and film downloads should answer 401
without a session and 200 after login, and both should survive `restart` and `down`/`up`.
The port is plain HTTP, so the password and cookie are visible on your LAN; the proxy route above
is the one with TLS. `/health/ready` stays anonymous and shows the version and Immich reachability.

See the [deployment matrix](../tested-deployments.md) for which of these routes have a verified
first run on this platform, and what still needs a report.
