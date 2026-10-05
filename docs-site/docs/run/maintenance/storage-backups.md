---
title: "Storage and backups"
---

# Storage and backups

Back up the store before an upgrade. It holds prepared facts, people, settings, review decisions
and run history. Losing a preview is a download; losing your decisions is a different problem.

## What to keep

| Data | Default location | Keep it? |
|---|---|---|
| Store | `~/.immich-memories/store.db`, or your PostgreSQL schema | Yes |
| Config | `~/.immich-memories/config.yaml` and deployment `.env`/Secrets | Yes |
| Saved-credential encryption key | `IMMICH_MEMORIES_SECRET_KEY` | Yes, with the store backup |
| Session signing key | `IMMICH_MEMORIES_STORAGE_SECRET` or `.storage_secret` | Keep to preserve logins |
| Local films and run artifacts | `output.directory` | Keep films you have not delivered elsewhere |
| Model weights | Config/models volume | Keep to avoid downloading again |
| Thumbnails and downloaded clips | `cache.directory` | Disposable |

In Docker, the named config volume contains the store and config; `./output` contains films.
In Kubernetes, those are the cache and output PVCs. Keep SQLite on local disk, with one writer
host. [Database options](../database.md) cover PostgreSQL and shared installations.

## Back up

Python:

```bash
immich-memories store backup
```

Docker:

```bash
docker compose exec immich-memories immich-memories store backup
docker compose cp immich-memories:/home/immich/.immich-memories/backups ./backups
```

Kubernetes:

```bash
kubectl exec -n immich-memories deploy/immich-memories -c immich-memories -- immich-memories store backup
kubectl cp -n immich-memories <pod>:/home/immich/.immich-memories/backups ./backups -c immich-memories
```

Backups can run while the app is up. Copy them off the host. Keep each `.db` or `.dump` together
with its `.manifest.json`; restore requires both. Save the encryption key separately and securely.
PostgreSQL needs `pg_dump` on `PATH`, at least as new as the server; the image includes it.

## Restore

Stop the UI, timers and workers first. `--force` replaces an existing store: use the backup you intend
and keep a copy of the current state. Restore with the release that made the backup when rolling back.
A corrupt or truncated backup is caught before anything is replaced, so the existing store is left
exactly as it was and the command exits with a clear error instead of a traceback.

Python, after stopping the app:

```bash
immich-memories store restore --from /path/to/store.db --force
immich-memories preflight
```

Docker, with backup and manifest on the same mounted volume:

```bash
docker compose stop immich-memories
docker compose run --rm immich-memories immich-memories store restore   --from /home/immich/.immich-memories/backups/store.db --force
docker compose up -d
docker compose exec immich-memories immich-memories preflight
```

### Kubernetes restore job

Suspend installed CronJobs first and record which were active. Wait for any running scheduled
Job to finish, then scale the Deployment down and wait for its pod to release the PVC:

```bash
kubectl get -n immich-memories cronjob -l app.kubernetes.io/name=immich-memories
kubectl patch -n immich-memories cronjob immich-memories-auto -p '{"spec":{"suspend":true}}'
kubectl patch -n immich-memories cronjob immich-memories-monthly -p '{"spec":{"suspend":true}}'
kubectl scale -n immich-memories deploy/immich-memories --replicas=0
kubectl wait -n immich-memories --for=delete pod -l 'app.kubernetes.io/name=immich-memories,!job-name,!batch.kubernetes.io/job-name' --timeout=120s
```

Save this as `restore-job.yaml`. Replace `X.Y.Z` with the release and `store.db` with the actual
backup filename. For PostgreSQL, use its `.dump` and add the same database Secret as the Deployment.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: immich-memories-restore
  namespace: immich-memories
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      enableServiceLinks: false
      securityContext:
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
      containers:
        - name: restore
          image: ghcr.io/sam-dumont/immich-memories:X.Y.Z
          command: [immich-memories, store, restore]
          args: [--from, /home/immich/.immich-memories/backups/store.db, --force]
          envFrom:
            - secretRef:
                name: immich-memories-secrets
          volumeMounts:
            - name: data
              mountPath: /home/immich/.immich-memories
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: immich-memories-cache
```

```bash
kubectl apply -f restore-job.yaml
kubectl wait -n immich-memories --for=condition=complete job/immich-memories-restore --timeout=300s
kubectl logs -n immich-memories job/immich-memories-restore
```

Only after a successful restore:

```bash
kubectl delete -n immich-memories job/immich-memories-restore
kubectl scale -n immich-memories deploy/immich-memories --replicas=1
kubectl exec -n immich-memories deploy/immich-memories -c immich-memories -- immich-memories preflight
```

Resume only CronJobs that were active before maintenance with `spec.suspend=false`.
The selector excludes both current `batch.kubernetes.io/job-name` and legacy `job-name`
labels added by the Job controller, so Job and CronJob
pods do not block the Deployment wait. It also works with the Terraform Deployment.

A SQLite backup restores to SQLite; a PostgreSQL backup to PostgreSQL. To change backend, restore
first, then use [store copy](../database.md).

## Caches

Preview and video caches default to 10 GB each. Local-only films and failed deliveries remain on
disk. After a confirmed upload to Immich, the local film and run directory are removed.
Use `runs storage` to inspect retained runs; use `runs delete` only for runs you want to remove.

```yaml
cache:
  video_cache_max_size_gb: 10
  video_cache_max_age_days: 7
  thumbnail_cache_max_size_mb: 10000
```

A preview averages about 315 KB: allow roughly 0.35 MB per candidate picture. A run can temporarily
exceed the preview cap to keep its active inputs. Finished films are separate, at
`~/Videos/Memories` on Python or `/app/output` in the image.

### Clearing

While the app is idle, use **Settings > Caches > Clear**. From a Python shell, these two
folders alone are safe to delete:

```bash
rm -rf ~/.immich-memories/cache/video-cache
rm -rf ~/.immich-memories/cache/thumbnails
```

In Docker, clear through Settings rather than deleting a similarly named host directory.
Do not delete `store.db` or the whole data volume. Attempt directories also contain review/render
inputs; removing the whole cache loses those artifacts even though banked facts remain in the store.

## Moving an install

Copy the config, encryption key and any films you need. Use `store backup`/`store restore` for
the store, then run `config test` and `preflight` on the new host.
[Source settings](../config-file.md#where-a-setting-comes-from) may need new paths or addresses.
