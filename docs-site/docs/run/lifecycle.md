---
title: Stop, reset or remove the app
---

# Stop, reset or remove the app

These operations affect **Immich Memories only**. Keep the separate Immich installation,
its database/volumes and originals. Films already uploaded to Immich remain there; uninstalling
this app does not delete remote media. No recipe below performs remote-library deletion.

Use the exact project, namespace and paths selected at installation. For Kubernetes, set the
namespace once per shell and every command below uses it:

```bash
NS=<your namespace>   # the one your kustomization sets; the shipped default is immich-memories
```

Never paste a command with a literal `-n immich-memories` into a cluster you did not install
into by default: that namespace may hold someone else's real install. The commands below cover
the shipped **Basic Compose**, **Kustomize base** and **native uv/pip** routes with SQLite.
Inventory optional model/worker services separately; do not stop a shared server used by other
apps. Suspend a GitOps reconciler before manual Kubernetes maintenance or it can recreate work.
For Terraform, review a plan matching the same retained resources; a blanket `destroy` can
remove PVCs and the namespace and is not the preservation procedure.

## First disable scheduled generation

Set `advanced.automation.enabled: false` in the controlling YAML, or
`IMMICH_MEMORIES_AUTOMATION__ENABLED=false` in the actual service environment, and restart the UI.
Settings cannot override a pinned file/environment value. Stopping the UI stops its in-app timer,
but an external scheduler can start another CLI process later.

For a native scheduler, deactivate it **before** deleting its files. Run only the route installed
on this machine:

```bash
# macOS launchd
launchctl unload "$HOME/Library/LaunchAgents/com.immich-memories.auto.plist"
immich-memories auto install --uninstall
launchctl list com.immich-memories.auto
```

The final lookup should report no loaded service: `Could not find service` with exit status 113
is the expected result, not an error. The launchd label is fixed (`com.immich-memories.auto`), so
two installs or users on one Mac share it. Run `launchctl list | grep immich` before loading a
second one, and don't load a plist whose label a job already holds. On Linux:

```bash
systemctl --user disable --now immich-memories-auto.timer
systemctl --user stop immich-memories-auto.service
immich-memories auto install --uninstall
systemctl --user daemon-reload
systemctl --user is-active immich-memories-auto.timer immich-memories-auto.service
```

Both units should be inactive or absent. For cron, use `crontab -e` to remove only the entry
calling `~/.immich-memories/bin/immich-memories-auto`, then run `auto install --uninstall` and
check `crontab -l`. Never delete the user's whole crontab. Deactivate any separately installed
UI service too; `auto install` manages scheduled generation, not the UI service.

For the optional shipped Kubernetes CronJobs, inspect and suspend the installed names:

```bash
kubectl get cronjobs,jobs -n "$NS" -l app.kubernetes.io/name=immich-memories
kubectl patch cronjob immich-memories-auto -n "$NS" -p '{"spec":{"suspend":true}}'
kubectl patch cronjob immich-memories-monthly -n "$NS" -p '{"spec":{"suspend":true}}'
```

Skip absent CronJobs. Suspending does not stop a Job already running: let it finish or cancel
that exact app-owned Job before maintenance. Check for no active app jobs and no enabled timers
before proceeding. Remove external HTTP triggers in their scheduler too.

## 1. Stop the app, keeping everything

Compose: in the original project directory, with the same `-p` and `-f` options used at install:

```bash
docker compose stop immich-memories
docker compose ps -a
# Start the same installation again:
docker compose start immich-memories
```

Kubernetes (deployment names are the shipped defaults, the namespace is yours):

```bash
kubectl scale deployment/immich-memories -n "$NS" --replicas=0
kubectl wait -n "$NS" --for=delete pod -l 'app.kubernetes.io/name=immich-memories,!job-name,!batch.kubernetes.io/job-name' --timeout=120s
# Start it again:
kubectl scale deployment/immich-memories -n "$NS" --replicas=1
```

This stops the app only. On the GPU tier the `immich-memories-inference` and
`immich-memories-captioner` Deployments keep running and keep their GPU slot, and so does any
optional service you added yourself (an Ollama pod, for example). Scale those to 0 as well if you
want the slot back, and back to 1 before the next film:

```bash
kubectl get deploy -n "$NS"
kubectl scale deployment/immich-memories-inference deployment/immich-memories-captioner -n "$NS" --replicas=0
```

Native: press **Ctrl-C** in the terminal running `immich-memories ui`, or stop the exact UI service
you installed. Restart with the same environment and `immich-memories ui`. These steps preserve
configuration, credentials, preparation, review decisions, history, weights and output.

## 2. Remove the app, keeping data for reinstall

First [back up/export](./maintenance/storage-backups.md) the store, credential encryption key,
configuration and films you want. Keep the exact image/package version and installation files.
For Compose, inspect the running app **before** removing its container. Use the same `-p` and
`-f` as at install: with a different project name, `docker compose ps -q` finds nothing and the
`test -n` below stops the script.

```bash
APP_CONTAINER=$(docker compose ps -q immich-memories)
test -n "$APP_CONTAINER"
docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$APP_CONTAINER"
docker inspect --format '{{range .Mounts}}{{println .Type .Name .Source "->" .Destination}}{{end}}' "$APP_CONTAINER"
DATA_VOLUME=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/home/immich/.immich-memories"}}{{.Name}}{{end}}{{end}}' "$APP_CONTAINER")
test -n "$DATA_VOLUME"
docker compose down
```

The displayed volume name includes the actual project prefix; do not guess it from a guide.
`down` without `--volumes` preserves that named volume and the `./output` bind directory.
Keep `.env`, encryption key and Compose files. `docker compose up -d` with the same project/files
and version reuses the data. Named optional services in that project also stop; inspect them first.

Kubernetes: stop as above, then remove only app controllers/routing. Keep the namespace, Secret,
ConfigMaps and PVCs. List what is installed first, so you remove what is there and not what the
docs assume:

```bash
kubectl get deploy,svc,networkpolicy,cronjob,ingress,pvc,secret,configmap -n "$NS"
kubectl delete deployment/immich-memories service/immich-memories networkpolicy/immich-memories -n "$NS"
```

On the GPU tier also delete the two model services and their policies. Their claims
(`immich-memories-caption-models` 2Gi, `immich-memories-inference-cache` 10Gi) stay:

```bash
kubectl delete deployment/immich-memories-inference deployment/immich-memories-captioner \
  service/inference service/captioner \
  networkpolicy/immich-memories-inference networkpolicy/immich-memories-captioner -n "$NS"
```

Delete an installed Ingress or CronJob separately, after recording it. An Ollama pod, its Service
and its NetworkPolicy are yours, not the app's: they outlive this step, so remove them only if
nothing else uses them.

Reapply with `kubectl apply -k <your root>`, the kustomization you installed from, to reuse the
claims. Never `kubectl apply -f` a base file: they hard-code the `immich-memories` namespace.
Do not use `kubectl delete -k`
for preservation: the kustomization includes namespace and PVC resources. Keep SQLite on its
supported local/block storage; verify settings/history and retained films after reinstall.

Native uv installs use `uv tool uninstall immich-memories`. For pip, use
`python -m pip uninstall immich-memories` **inside the original app virtual environment**.
Both preserve `~/.immich-memories` and `~/Videos/Memories`; reinstall the same package/extras to reuse them.
They do not remove separately installed Ollama, llama.cpp, FFmpeg or shared model caches.

## 3. Reset app state for a fresh trial

:::danger State loss
Back up using [storage and backups](./maintenance/storage-backups.md) and export any films first.
Reset removes saved Settings and credentials, banked preparation, people/review decisions,
sessions, job/run history and local app caches. Deployment credentials in `.env`/Secrets or a
preserved config file remain; reusing them is not a fresh credentials test. Finished output is
preserved by these reset steps. A reset is not needed for an ordinary failed run.
:::

For Compose, after step 2 captured the exact `DATA_VOLUME` and stopped the project:

```bash
docker volume inspect "$DATA_VOLUME"
docker volume rm "$DATA_VOLUME"
docker compose up -d
docker compose exec immich-memories immich-memories models fetch
docker compose exec immich-memories immich-memories preflight
```

Use this only when inspection confirms the default app-only named data volume. A bind mount
or shared data volume requires a separately scoped procedure. The removed volume also contains
app model caches; they are fetched again. `.env`, Compose files and `./output` remain.

For Kubernetes with the app stopped and no active app Jobs, delete **only** the state PVC:

```bash
kubectl get pvc immich-memories-cache -n "$NS" -o wide
kubectl delete pvc immich-memories-cache -n "$NS"
kubectl apply -k <your root>
```

`apply -k` on your own root recreates the claim in your namespace. `kubectl apply -f
deploy/kubernetes/base/pvc.yaml` would not: that file says `namespace: immich-memories` and
creates the claim there, in someone else's install if the default namespace is in use. Reapplying
also restores the base NetworkPolicy; reapply a stricter [offline policy](./offline.md) afterwards.

This preserves `immich-memories-output`, `immich-memories-models`, the GPU tier's claims, the app
Secret and any ConfigMap you mount. Verify the
StorageClass/PV reclaim policy first: `Retain` can leave the old state on a retained PV and is
not proof of erasure. Bind a fresh volume rather than reattaching the old data, then restart and
prepare/preflight. Do not claim a reset until saved history/settings are absent as expected.

For native defaults, stop all app processes, then move state aside to an explicitly named backup:

```bash
test ! -e "$HOME/.immich-memories.before-reset"
mv "$HOME/.immich-memories" "$HOME/.immich-memories.before-reset"
mkdir -m 700 "$HOME/.immich-memories"
```

Create a new config with the [minimum read key](./uv-pip.md) and put `tier: basic` back in it.
With no config at all, Apple Silicon selects the `gpu` tier on its own, so a reset would quietly
change your tier. Then run `models fetch` and preflight.
The old credentials/history remain in the backup until deliberately removed. Native output and
external/shared model caches remain. Environment variables can still point at an old/custom store;
check `config show` privately before calling the new run fresh.

These SQLite resets do not reset PostgreSQL. For PostgreSQL, stop writers and have the database
owner back up and recreate **only the dedicated app schema/role** using the
[database isolation procedure](./reference/database.md#4-a-dedicated-schema-in-immichs-own-database).
Never drop Immich's database or `public` schema.

## 4. Remove all app-owned local data

:::danger Permanent local removal
After [backing up/exporting](./maintenance/storage-backups.md), stop schedules/processes and
remove the app as above. The following additionally deletes local state, keys/models and all
films in the named app-only output directory. Remote Immich originals and uploaded films remain.
Do not run a directory removal if you placed other applications' files there.
:::

For the default Compose project, use the inspected volume name from step 2 and remain in its
app-only directory. A generated file (the Synology or setup-builder output) can also carry a named
output volume, and `DATA_VOLUME` alone misses it. List every volume of the project, with the
project name from step 2:

```bash
docker volume ls --filter label=com.docker.compose.project=<project>
```

Remove the ones that belong to this app (check each against the mount inventory), then:

```bash
docker volume rm "$DATA_VOLUME"   # plus any other app-owned volume from the list
rm -r -- ./output
rm -- .env
docker image rm ghcr.io/sam-dumont/immich-memories:<version>
```

The pulled image stays after `down` and the volume removals, so remove it with the line above
(or keep it for a reinstall). The project folder holds the release files, and any copy of `.env`
(`.env.bak`, an old `docker-compose.yml` with the key pasted in) still contains the Immich API
key: delete those by name. Do not remove a parent directory, shared external model cache or other
Docker volumes. Inspect any optional
service mounts separately; a shared model server belongs to its operator, not this uninstall.

For the default Kubernetes base, after removing app controllers and schedules:

```bash
kubectl delete pvc immich-memories-cache immich-memories-models immich-memories-output -n "$NS"
kubectl delete secret immich-memories-secrets -n "$NS"
```

The GPU tier adds two claims. Delete them only if you also deleted the two services above:

```bash
kubectl delete pvc immich-memories-caption-models immich-memories-inference-cache -n "$NS"
```

Then remove the recorded ConfigMap you mounted (if any), your Ollama Deployment, Service,
NetworkPolicy and model claim (if you added one), and saved secret files. Run
`kubectl get all,pvc,networkpolicy,configmap,secret -n "$NS"` at the end: what is left is not the app's. Keep the namespace when shared. Never delete a namespace as a
shortcut to discovering which resources belong to the app. If `apply -k` created the namespace
and the listing above shows nothing else in it, `kubectl delete namespace "$NS"` finishes the job.

Deleting a PVC does not delete its disk when the StorageClass reclaims with `Retain`: the PV stays
as `Released`, with your films and state on it. List the ones that belonged to this namespace:

```bash
kubectl get pv | grep Released | grep "$NS/"
```

Each row's `CLAIM` column reads `<namespace>/<claim>`. Once you are sure the data is not needed,
tell the provisioner to drop it:

```bash
kubectl patch pv <name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'
```

With a CSI provisioner this deletes the backing disk (verified on proxmox-csi). It is
permanent: films, caches and the SQLite store on that volume are gone. Check the `CLAIM`
column twice, since a PV from another app looks the same. Snapshots are the storage owner's to
remove.

For native defaults, after package/scheduler removal, confirm these paths contain only this app's
files, then delete the state and local films:

```bash
rm -r -- "$HOME/.immich-memories" "$HOME/Videos/Memories"
```

`.immich-memories.before-reset` keeps the plaintext API key from the old config. Once you no
longer need it, remove it the same way: `rm -r -- "$HOME/.immich-memories.before-reset"`. Other
copied backups may hold credentials and films too. Preserve shared Hugging Face/Ollama/llama.cpp
caches and packages.

`uv tool uninstall` does not clear uv's own download cache (2.6 GB on the test Mac), so "complete
removal" leaves it. `uv cache clean` empties it for every uv project, not only this app; skip it
if you use uv for other things.

Check the original deployment inventory again: no running app container/pod/UI process, no active
app Jobs or schedules, no remaining app-owned volumes/paths except deliberate backups. Separately
verify Immich still serves its library.

## What has been run

Destructive transcripts exist for two of the three routes, both on 2026-10-04 with
`v0.0.0-dev.37180797983` (#956 verification):

- **Native**: macOS arm64, prebuilt wheel, isolated HOME. Scheduler setup and removal,
  uninstall keeping data, reinstall, reset and complete removal. UI stop/start was not run, and
  neither were the cron and systemd scheduler routes.
- **Compose**: Synology DS423+, DSM 7.3.2, Docker 24.0.2 with Compose 2.20.1. Stop/start, remove
  keeping data, reset and complete removal. The other containers on that NAS and Immich were
  unaffected.

The Kubernetes transcript is still pending under
[#1929](https://github.com/sam-dumont/immich-memories/issues/1929); until it runs, the Kubernetes
commands above are written, not proven.
