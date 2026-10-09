---
title: Quick start
description: Install Immich Memories with Docker Compose and make your first photo and video highlight film. Runs on a server or NAS; no GPU required.
---

# Quick start

Run Immich Memories beside your Immich server, then try a 30-second film from 20–50 photos/videos. No GPU or model server needed.

You need Docker with Compose v2, Immich v2 or v3, and two CPU cores, 4 GiB of RAM for this app in addition to Immich/host needs and 25 GB for its data, plus the image and finished films. [Full requirements](../run/requirements.md).

import InstallationFiles from '@site/src/components/InstallationFiles';

See [tested deployments](../run/tested-deployments.md) for exact platform evidence, Immich API versions and untested routes.

## 1. Download the files

<InstallationFiles />

Basic needs only `docker-compose.yml` and `example.env` (saved as `.env`). The other files are for GPU, Full, the render worker and PostgreSQL, so download them only if you take one of those routes. The commands above pin `.env` to this release by rewriting the `IMMICH_MEMORIES_VERSION` line that `example.env` already holds.

The image is about 2.3 GB. With an empty layer cache the pull in step 3 took 84 seconds on a Synology; budget more on a slow line.

Check the network now. `ip route get 192.168.1.10` prints the device that reaches Immich after `dev` (use your Immich address). Read that device's MTU from `/sys/class/net/<dev>/mtu`: for `dev eth0`, run `cat /sys/class/net/eth0/mtu`; on Synology it may be `cat /sys/class/net/ovs_eth0/mtu`. Below 1500 (a VPN, Kubernetes node or cloud VM), save this as `docker-compose.override.yml` next to `docker-compose.yml`, with a value below the one you read:

```yaml
networks:
  default:
    driver_opts:
      com.docker.network.driver.mtu: "1300"
```

Otherwise the first cut hangs on thumbnails while preflight stays green. [Why it happens](../reference/troubleshooting.md#preflight-says-immich-is-connected-but-cuts-hang-on-thumbnails).

Create `output` yourself, owned by uid 1000, so Docker does not make it as root. This is where local films land. Run it in the same folder, right after the downloads:

```bash
mkdir -p output && sudo chown 1000:1000 output   # drop sudo if you are root
```

The container runs as uid 1000. If you run `mkdir` as root and skip the `chown`, preflight fails with "Output directory is not writable". On Synology, `chown` is not enough: use the [ACL recipe](../run/nas.md#the-output-folder).

**Sharing this host with another copy, or with something on port 8080?** Do this now, before step 3. The compose file hard-codes `container_name: immich-memories` and the host port, so a second copy collides on both, and two projects in folders with the same name share one volume:

```bash
echo 'COMPOSE_PROJECT_NAME=immich-memories-2' >> .env
```

Then in `docker-compose.yml` change `container_name` and the number before `:8080` in the port line (keep `${UI_BIND_ADDRESS:-127.0.0.1}`), for example `${UI_BIND_ADDRESS:-127.0.0.1}:8081:8080`. Run every `docker compose` command below from this folder; the service name stays `immich-memories`, and the app is then at `http://localhost:8081` instead of 8080 in step 4. Only `UI_BIND_ADDRESS` is a variable; the port number is not.

## 2. Connect Immich

Open `.env` in a text editor and set:

```bash
IMMICH_URL=http://192.168.1.10:2283
IMMICH_API_KEY=your-api-key-here
```

Use the address the container can reach, usually your server's LAN address. `localhost` inside the container points at the container itself.

In Immich, create the key under **Account Settings > API Keys > New API Key**. Select the
[ten read permissions](../run/docker.md#the-api-key). Add the five upload permissions only if
you want to send films back to Immich; leave **All** unchecked.

## 3. Start and download the local models

```bash
docker compose pull
docker compose up -d
docker compose exec -T immich-memories immich-memories models fetch
docker compose exec -T immich-memories immich-memories preflight
```

`models fetch` downloads the pinned local model and dictionary. Picture processing runs on your CPU.
Preflight must pass Immich, required-model and output checks. Basic skips unconfigured optional
services; home coordinates are optional for an album film.

The Output directory row says where films go and who decided it: `/app/output (from IMMICH_MEMORIES_OUTPUT__DIRECTORY, mounted volume), writable`. The source is the environment variable, `config.yaml` or the built-in default. In a container a path that is not a mount gets its own warning, because films written there vanish on restart. The image sets the variable, and it beats `output.directory` in `config.yaml`: preflight warns when the two disagree.

The commands use `-T` so they also work without a terminal. Over SSH, set the table width to keep the row labels readable:
`docker compose exec -T -e COLUMNS=140 immich-memories immich-memories preflight`.
Inside a script sent with `ssh host 'bash -s'`, append `</dev/null` to each Compose `exec` command so it cannot consume the rest of the script.

These are normal on Basic:

- **Hardware**: `Software encoding (libx264)` is OK on a CPU-only host.
- **Title rendering**: `CPU titles (Pillow + FFmpeg); moving backgrounds need a GPU` is OK, including on Celerons without AVX.
- **Homebase**: skipped until you set home coordinates for trips and seasons.
- **Immich** with a read-only key still warns that upload permissions are missing. Films stay local; the connection works.

A detected NVIDIA card whose encoder cannot start is a separate warning: check the device and driver setup.

## 4. Open the app

On the machine running Docker, open [http://localhost:8080](http://localhost:8080).

8080 taken? Change the number before `:8080` in the `ports:` line of `docker-compose.yml` (`127.0.0.1:8081:8080` serves the app at `http://localhost:8081`), then `docker compose up -d` again. Without Docker, `immich-memories ui -p 8081` does the same.

For a headless NAS, run this on your desktop first, replacing the SSH account and server name:

```bash
ssh -L 8080:localhost:8080 you@your-nas
```

SSH login working does not mean forwarding is permitted. If the tunnel prints
`open failed: administratively prohibited`, follow the
[Synology authenticated proxy route](../run/platforms/synology.md#authenticated-proxy)
before exposing any LAN port. Do not change global SSH policy to make the tunnel work.

Then open the same localhost address on your desktop. The default port is available locally; [authentication](../run/authentication.mdx) covers remote access.

Follow [Your first film](./first-film.mdx): create an Immich album with **20–50 supported
photos/videos**, choose **Album**, and set the length to **0.5 minutes**. Review the cut and render
with upload off. Shortening a film alone does not reduce how many inputs need preparation.

No Docker? The same steps work natively: use [pip / uv](../run/uv-pip.md) and drop `docker compose exec -T immich-memories` from every command on this page and on [Your first film](./first-film.mdx). Films then land in `~/Videos/Memories`, not `./output`.

Cold setup includes the image pull, model download, input preparation and render. Hardware,
input count and cache state matter. [Measured numbers](../better/measured.md#cold-start-time-by-hardware-and-tier)
separate film generation from setup; larger periods can still take hours.
[The phase guide](./first-film.mdx#progress-and-recovery) explains what progress and completion look like.
[After install](./after-install.md) covers home, people and backups. Got your first film?
[Choose your setup](./choose-your-setup.md) explains what more you can get.

## If it stops

| Message or symptom | Fix |
|---|---|
| `Encoder: Pinned DINOv2 export missing` | Run `models fetch` from step 3. |
| Output directory is not writable | On Linux, `sudo chown -R 1000:1000 output`. On Synology DSM, use the [ACL recipe](../run/nas.md#the-output-folder). |
| `Immich: Connection failed` | Check the URL and key in `.env`, then run `docker compose up -d` again. |
| `port is already allocated` on `docker compose up` | Something else holds 8080. Change the host port as in step 4. |
| The cut hangs on thumbnails while preflight is green | The host's network MTU is below Docker's. See [the MTU fix](../reference/troubleshooting.md#preflight-says-immich-is-connected-but-cuts-hang-on-thumbnails). |

Check the installation at any time:

```bash
docker compose exec -T immich-memories immich-memories preflight
```

For NAS-specific permissions and CPU settings: [On a NAS](../run/nas.md). Without Docker: [pip / uv](../run/uv-pip.md).
