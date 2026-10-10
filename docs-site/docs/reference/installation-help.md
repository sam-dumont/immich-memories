---
title: Installation help
description: Fix installation problems with permissions, ports, model preparation and networking.
---

# Installation help

For a first installation, follow [Quick start](../get-started/quick-start.md) or your
[platform guide](../run/overview.md). Use this page when a step fails.

## Download models from the CLI

The app's **Download models** button and the CLI fetch the same files for your configured tier.
Use either one. For Docker Compose, run from the installation folder:

```bash
docker compose exec -T immich-memories immich-memories models fetch
```

On a native install, run `immich-memories models fetch` as the user who runs the app.
Wait for it to finish before making a film. Later runs reuse verified files.

## Read preflight {#read-preflight}

With Docker Compose, run from your installation folder:

```bash
docker compose exec -T immich-memories immich-memories preflight
docker compose exec -T immich-memories immich-memories capabilities
```

On a native install, use `immich-memories preflight` and `immich-memories capabilities`
directly. For a container manager, run those two commands in its app container console.

`preflight` checks the Immich connection, required models, output and configured services.
`capabilities` reports the resolved tier. Read the individual checks; a warning count alone
cannot tell you whether a film can run.

| Result | What to do |
|---|---|
| Missing pinned encoder, dictionary or detector | Run `immich-memories models fetch` using the same tier and configuration |
| Output is not writable | Give UID/GID 1000 access to the output folder; use the [Synology ACL recipe](../run/nas.md#the-output-folder) on DSM |
| Immich connection failed | Check its container-reachable URL and the [API-key permissions](../run/docker.md#the-api-key) |
| Missing GPU inference, captions or Laya | Wait for the model services, then check their configuration; see [GPU requirements](../run/requirements.md#which-tier-you-get) |
| Full needs an enabled reader | Configure the reader URL, model and explicit enable switch before starting Full |
| Basic uses software encoding or CPU titles | Supported; no fix needed |
| Home coordinates skipped | Optional for album films; set them later for trips |
| Upload permissions missing on a read-only key | Local films still work; add upload permissions when enabling uploads |

The output row names the destination and its configuration source. Environment variables beat
`config.yaml`, including the output path set by the image. A path outside a mounted volume gets
a warning because its files do not survive container replacement.
[Configuration sources](../run/config-file.md#where-a-setting-comes-from) explains how to change it.

## Port or container name already in use

The release Compose file uses host port 8080 and `container_name: immich-memories`.
Change only the host port in its `ports:` entry, preserving the bind address:

```yaml
ports:
  - ${UI_BIND_ADDRESS:-127.0.0.1}:8081:8080
```

Recreate with `docker compose up -d` and open port 8081. The setup builder has a **UI host port**
field for the same choice. Natively, use `immich-memories ui -p 8081`.

For a second installation on the same host, use a separate project folder, a unique
`COMPOSE_PROJECT_NAME` in `.env`, a different container name for each service and free host ports.
Two directories with the same basename otherwise get the same Compose project name and volume
names. Run commands from the correct project directory with `docker compose exec`; it finds
services by their service name even when their container names differ.

## Cuts hang on thumbnails although preflight passes

An Immich metadata check can pass while larger thumbnail transfers hang when the host route's
MTU is smaller than Docker's. This can occur with a VPN, a Kubernetes node or a cloud network.

Run `ip route get 192.168.1.10` with your Immich address. The device follows `dev`; read its MTU
with `cat /sys/class/net/eth0/mtu`, substituting that device (for example `ovs_eth0` on Synology).
If it is below 1500, add `docker-compose.override.yml` with a smaller value, for example:

```yaml
networks:
  default:
    driver_opts:
      com.docker.network.driver.mtu: "1300"
```

If `.env` sets `COMPOSE_FILE` for GPU or Full, append `:docker-compose.override.yml` to that list
so Compose uses the override too. Follow the [network recreation procedure](./troubleshooting.md#preflight-says-immich-is-connected-but-cuts-hang-on-thumbnails).

## SSH forwarding is refused

SSH login does not imply permission to forward ports. On DSM, a non-admin account can log in
while a tunnel gets `administratively prohibited`. Use an approved forwarding-enabled account,
[app login on the LAN](../run/docker.md#reaching-the-ui-from-another-machine), or the
[Synology HTTPS proxy](../run/reference/synology-operations.md#authenticated-proxy).
Do not change global SSH policy to follow an app installation guide.

## Running checks over SSH

Use `-T` without a terminal and set the width when the table wraps:

```bash
docker compose exec -T -e COLUMNS=140 immich-memories immich-memories preflight
```

Inside a script sent with `ssh host 'bash -s'`, append `</dev/null` to Compose `exec` commands
so they cannot consume the rest of the script.

## Native install: command, Python or FFmpeg problems

[Python installation details](../run/reference/python-install.md#installation-troubleshooting)
covers PATH, Python versions, FFmpeg filters and runtime extras.
For a film that has already started, use [film progress and recovery](../run/film-progress.md).
