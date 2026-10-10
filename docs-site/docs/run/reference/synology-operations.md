---
title: Synology access and troubleshooting
description: SSH and Compose installation, DSM permissions, reverse proxies and access checks.
---

# Synology access and troubleshooting

For a new Container Manager project, use [Synology setup](../platforms/synology.md).
The recipes below cover release files over SSH and alternative access routes. The `.env`
examples apply to the two-file release installation. With the builder's single file, set the
same values directly in the app service's `environment` and `ports` entries.

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
/usr/syno/bin/synoacltool -addace output user:$(id -un):allow:rwxp-DaARWc--:fd--
sudo docker compose -p immich-memories pull
sudo docker compose -p immich-memories up -d
sudo docker compose -p immich-memories exec immich-memories immich-memories models fetch
sudo docker compose -p immich-memories exec immich-memories immich-memories preflight
```

The two `synoacltool` lines give the container's uid 1000 write access to `output` and keep your
DSM user able to read and remove the files. Without the second entry, the ACL can deny your own
account access to the folder. See [the output folder](../nas.md#the-output-folder) for why `chown`
isn't enough. Run every later Compose command from this directory with `-p immich-memories`;
the explicit project name also determines its named volume prefix.

For French films, open **Settings**, set `title_screens.locale` to **French** and save.
For a file-based setting, add `locale: fr` under `title_screens:` in `config.yaml`.
Automatic language detection reads the container's locale, not DSM's. Adding `LANG` to `.env`
has no effect because the release Compose file does not pass it into the container.

This stock release-file route uses host port **8080**. If occupied, change only the number before
`:8080` in the port line, so it reads `${UI_BIND_ADDRESS:-127.0.0.1}:18081:8080`.
Keep `${UI_BIND_ADDRESS:-127.0.0.1}`: the LAN route depends on it. Use the new NAS port in the
tunnel and proxy destinations below.

When you script these commands over `ssh`, `docker compose exec` can consume the script's stdin.
Change to the project directory in the remote script, and add `-T` and `</dev/null` to each
Compose `exec` command so the next script line stays available. Scripted Docker commands also
need permission to run without an interactive `sudo` password prompt.

On your **desktop**, the permitted-tunnel route is:

```bash
ssh -o ExitOnForwardFailure=yes -L 8080:127.0.0.1:8080 your-user@your-nas
```

Keep that session open and visit `http://localhost:8080` on the desktop. If you changed the NAS
port to 18081, use `-L 8080:127.0.0.1:18081`; the browser URL stays the same. If forwarding is
denied, use either the [HTTPS proxy](#authenticated-proxy) or
[LAN port with app login](#lan-port-with-app-login-no-tunnel-no-proxy) below.

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
   Add `-u user:password` and it still answers 401: the login is a form that sets a session
   cookie, not HTTP Basic, so `curl -u` never signs in. To test the 200, sign in the way the page
   does and reuse its cookie, see [Checking auth with curl](#checking-auth-with-curl).
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
the LAN with app authentication on. Do it in this order, from the project directory on the NAS:

1. In `.env`, set the login: `IMMICH_MEMORIES_AUTH_USERNAME=admin` and
   `IMMICH_MEMORIES_AUTH_PASSWORD=` a long password of your own (12 characters or more).
2. In the same file, set `UI_BIND_ADDRESS=0.0.0.0`.
3. Start it: `sudo docker compose -p immich-memories up -d`.

From a second machine, `/api/v1/settings`, thumbnails and film downloads should answer 401
without a session and 200 after login, and both should survive `restart` and `down`/`up`.
The port is plain HTTP, so the password and cookie are visible on your LAN; the proxy route above
is the one with TLS. `/health/ready` stays anonymous: it returns readiness status and the app
version, with Immich details set to `null` until you sign in. It cannot confirm that login is
required.

### Checking auth with curl {#checking-auth-with-curl}

The app's "Basic auth" is a username and password typed into a login form. It does not read an
HTTP `Authorization: Basic` header, so `curl -u user:password .../api/v1/settings` gets 401 whatever
the password. Sign in over `/auth/login`, keep the cookie, and ask again:

Set `memories_url` to the URL you use in the browser. For the proxy route, use
`https://memories.example.com`: its secure session cookie is not sent over plain HTTP.
Replace the sample credentials with your app login.

```bash
memories_url=http://nas-address:8080
umask 077
curl -fsS -c jar.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your-password"}' "$memories_url/auth/login"
curl -sS -b jar.txt -o /dev/null -w '%{http_code}\n' "$memories_url/api/v1/settings"   # 200
rm jar.txt
```

A wrong password gets 401. Repeated failures trigger the rate limit and return 429.

See the [deployment matrix](../tested-deployments.md) for which of these routes have a verified
first run on this platform, and what still needs a report.
