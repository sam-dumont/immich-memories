---
title: On a NAS
---

import ComposePort from '@site/src/components/ComposePort';

# On a NAS

Choose your container manager and follow its install steps:

| Platform | Install |
|---|---|
| Synology DSM | [Container Manager project](./platforms/synology.md) |
| Unraid | [Docker template or Compose Manager](./platforms/unraid.md) |
| TrueNAS 24.10+ | [Custom app](./platforms/truenas.md) |
| Portainer | [Docker Standalone stack](./platforms/portainer.md) |
| QNAP or another NAS with Compose | [Docker Compose](../get-started/quick-start.md) |

**Basic** runs on the NAS CPU. **GPU** uses NVIDIA inference and captions, either on a supported
host or a separate GPU machine. **Full** adds a reader. Each stack-editor guide includes the
builder's three tier choices. Allow memory and storage in addition to what Immich uses:
[requirements](./requirements.md).

The generated single-file route uses Docker-managed volumes. It does not need a hand-created
output folder. The release Compose file uses `./output`; use the permissions below for that
route, or when choosing a NAS share for films.

## Existing model services

If you already run separate inference and caption services, including in Kubernetes, reuse them.
In your platform's builder, choose **GPU** or **Full** and enter the inference host and port in
**GPU box address**, such as `192.168.1.50:8092`. This exports an app-only Compose file.
In its app `environment`, replace `IMMICH_MEMORIES_DEPLOYMENT_GPU_BOX` with both URLs:

```yaml
IMMICH_MEMORIES_DEPLOYMENT_INFERENCE_URL: http://192.168.1.50:8092
IMMICH_MEMORIES_DEPLOYMENT_CAPTION_URL: http://192.168.1.51:8092/v1
```

Use your services' private addresses, reachable from the NAS. Kubernetes-internal service names
usually cannot be reached from there. Skip the generated GPU-worker files and commands: those
would start another worker. [Inference](../better/inference.md#classifiers-and-stems-only) and
[captions](../better/captions.md) explain the two services.

For **Full**, enter the reader's `/v1` URL and served model name in the builder. It enables the
reader; replace the generated reader-key placeholder, or empty it if the server needs no key.
The [reader needs a 32k context](../better/reader.md#use-an-existing-server).

This app-only file keeps the base `memory: 4G` limit. Keep output at 1080p with that limit.
For 4K on GPU/Full, raise the app limit to `8G` and allow that RAM on the NAS. The model services
need their own memory. Laya still runs in the app; remote inference does not move rendering.
After starting, use **Download models** in the app and run `immich-memories preflight` in its
container, as your platform guide describes.

## NAS operating notes {#install}

The following sections cover storage, network access, encoding and resource tuning.
For first startup, use the platform guide above, then [make a film](../get-started/first-film.mdx).

### The output folder

The image runs as UID/GID 1000. NAS users often have a different UID, so preflight can report
`Output directory is not writable`. The fix depends on the NAS.

**Synology DSM.** `chown` alone does nothing useful on a home share: the share's Synology ACL
still denies uid 1000. Add an ACL entry for it, and a second one for your own DSM user, over SSH
as that user, no `sudo`, in the project folder:

```bash
mkdir -p output
/usr/syno/bin/synoacltool -addace output user:1000:allow:rwxpdDaARWc--:fd--
/usr/syno/bin/synoacltool -addace output user:$(id -un):allow:rwxp-DaARWc--:fd--
/usr/syno/bin/synoacltool -getace output
ls -ld output
```

Both entries go in. `ls -ld output` should end in `+` and not show `d---------+`: that means
the ACL holds only uid 1000 and your own account gets "Permission denied" on `touch output/x`.

- `synoacltool` is not on a docker-group user's `PATH`, so use the full path.
- `-addace` takes numeric ids. `-add user:1000` resolves names and answers "No such user".
- The `fd` flags make the entry inherit, so files the container creates stay readable and
  deletable by your own DSM user.
- Your own entry is not guaranteed. A new `output` folder made after `chmod 700 .` is in plain
  Linux mode, so the first `-addace` creates an ACL with only uid 1000 in it. The second line
  puts your account back (`$(id -un)` is your DSM user name).

This ACL fix is confirmed to work on current DSM: a uid-1000 container can write files, your
own DSM user can read and remove them, and a UI render writes its film through the bind mount.

**Plain Linux NAS** (no Synology ACLs):

```bash
sudo chown -R 1000:1000 output
```

Don't set `user: "<your uid>:<gid>"` in the Compose file. The image's `/home/immich` is `0700`
and owned by 1000, so the app crashes at start with
`PermissionError: ... '/home/immich/.immich-memories'`.

If you replace a named output volume with this bind mount, earlier runs show the film as
unavailable: their files stayed in the old volume. Nothing is broken, new films land in `output`.
Keep either a bind mount or a named volume at `/app/output`, including when
[upload-back](./docker.md#films-into-immich) is enabled. An interrupted or failed upload needs
that local copy to survive container replacement.

### Reaching the UI

The default host port, <ComposePort />, is local to the NAS. From your desktop:

<pre><code>ssh -L 8080:localhost:<ComposePort /> you@your-nas</code></pre>

Open `http://localhost:8080` on the desktop. If SSH forwarding is denied, the browser cannot
reach the app through that tunnel. For LAN access
without a tunnel, turn on authentication and set `UI_BIND_ADDRESS=0.0.0.0` in `.env`:
[Docker access recipe](./docker.md#reaching-the-ui-from-another-machine). That port is plain
HTTP; use the proxy route if you want TLS.

The shipped Compose file uses host port <ComposePort /> and the container name `immich-memories`.
If another NAS app already uses that port, change the host port in the mapping and tunnel to it.
The container port remains 8080. For a second installation, give this project a different `container_name` and host port. Run
commands from its project folder with `docker compose exec immich-memories immich-memories ...`,
which finds the service whatever the container is called. A command using `docker exec` needs
your chosen container name.

### Do not use `cpus:` on a Synology

DSM kernels without the CFS bandwidth controller reject a CPU quota with
`NanoCPUs can not be set`. The shipped Compose file sets none. To leave a core for Immich,
pin this app to three cores on a four-core NAS:

```yaml
    cpuset: "0-2"
```

`title_screens.locale: auto` follows the host's `LANG`, but the container sets none, so a
film always renders in English until you set `title_screens.locale: fr` (or add
`LANG: fr_FR.UTF-8` to the `environment:` block) for a French one.

## What to expect

Basic films are capped at 1080p. The default 4 GiB memory limit suits that output.
The first film takes the longest: it has to read every picture in its period before it can
render. Larger periods, slower storage and different media can take hours. See
[measured examples](../better/measured.md#cold-start-time-by-hardware-and-tier) for real numbers on comparable
hardware.


The first film reads the pictures in its period and saves the results; later films reuse matching
results. Rendering still happens every time.

Basic preparation leaves Marqo and Docling off; GPU/Full add those detectors, captions and the
Laya pre-screen. Compatible facts already in the store stay banked when you change tiers. See
[what the upgrades add](../get-started/choose-your-setup.md).

CPU titles draw their background and text once, then move, scale and fade the text with FFmpeg.
The background stays still to keep software encoding cheap. No extra package is needed. For cheaper trip
maps, use `preset: fast`: three geographic views replace the smooth flight, with short fades and
full-resolution labels. Hardware video encoding still works. [Titles and maps](../make/titles-maps-music.md)
explains these choices.

[Measured results](../better/measured.md) records whole-film wall times and separate stage costs.
Preparation-only figures exclude downloads, music and rendering where explicitly labelled. A long
film also gets a full playback check after rendering, which can take time. The log reports progress
once a minute.

## Encoding

An Intel NAS can use Quick Sync for H.264. Add the device block below to the app service in
Compose (the shipped file has no device mapping by default), and use the numeric group that
owns the render node:

```bash
stat -c '%g' /dev/dri/renderD128
```

```yaml
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - "937" # example DSM GID; use the number from stat
```

Verify with [Hardware encoding](./hardware.md#verify-it). Passing the device without its group
leaves it visible but unusable.

J4125-class NAS hardware cannot encode HEVC. With the default `prefer_hardware` policy, the app
can choose H.264 instead. A strict H.265 or explicit HDR request can require software encoding.
ARM64 Docker uses software encoding. Non-AVX Celerons use the simpler title renderer.

## Memory and disk

Allow 25 GB for persistent data, plus the image and finished films. Keep the persistent store.
Size the preview cache for the pictures your films can reach:
roughly 0.35 MB per picture. The default preview/video budgets total 20 GB.
[Storage and caches](./maintenance/health-logs-cache.md#caches) covers caps and cleanup.
Uploaded films are removed locally after confirmed delivery; local-only films keep growing.

## Every night

The running UI can make one memory a day. Enable the timer in Compose and set `TZ`:
[Docker automation](./docker.md#daily-automation). [Automate it](../make/automate.md) explains
what it picks and how to upload the result.

## Long films

Stay at 1080p on NAS. For rendering on a stronger machine, use a
[render worker](../better/gpu-render.md); that changes rendering, not the selection tier.

## What a NAS can't do

GPU selection and local generated music need their respective GPU services. A reader alone still
helps with titles and music mood. Use the [add-on guide](../get-started/choose-your-setup.md)
to choose the next useful piece.

## Everything else

The Docker instructions cover [API-key permissions](./docker.md#the-api-key),
[uploads](./docker.md#films-into-immich), [backups](./database.md#managing-the-store) and
[upgrades](./maintenance/upgrading.md#docker). Container commands need `sudo` only if your user isn't in the `docker` group.

## Stop or remove this installation

[Stop, reset and uninstall](./lifecycle.md) separates retaining data for reinstall from deleting app state.
