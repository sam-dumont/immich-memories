---
title: Upgrading
sidebar_label: Upgrading
---

import InstallationFiles from '@site/src/components/InstallationFiles';

# Upgrading

Read the [release notes](https://github.com/sam-dumont/immich-memories/releases),
back up the store, then upgrade. Keep the backup for rollback: a newer release can migrate the
store to a revision older code will refuse.

## From 1.0.0-rc.10 to 1.0.0

### Sign-in is on

Authentication is on by default now. An install that ran without it asks for a sign-in after the
upgrade. With nothing configured, the first start generates a password and prints it once, in the
server log. No page shows it. The username is `admin`.

```sh
docker compose logs immich-memories 2>&1 | grep -A2 "Sign in to Immich Memories"
```

Only a hash of that password is kept, in `generated-login.json` beside the config file
(`~/.immich-memories/`, the config volume in Docker). Lost it? Make a new one; it is printed once
in the terminal and every browser signed in with the old one is signed out:

```sh
docker compose exec immich-memories immich-memories auth reset-password
```

Your own credentials (`auth.username` and `auth.password`, or the `IMMICH_MEMORIES_AUTH_USERNAME`
and `IMMICH_MEMORIES_AUTH_PASSWORD` pair), OIDC and header sign-in work as before. A password
without a username signs in as `admin`.

To keep running without sign-in on purpose, say so: `auth.enabled: false` under `advanced:`, or
`IMMICH_MEMORIES_AUTH__ENABLED=false`. Without sign-in the UI answers on localhost only.
`server.allow_unauthenticated_lan` is gone: it is ignored with a warning. For LAN access without a
login of its own, put the app behind your proxy and use header sign-in.

`immich-memories ui` still listens on `127.0.0.1` with the generated password. With sign-in on,
the server answers any host name, since the sign-in is what protects it.

### One tier setting

`tier` (`auto`, `basic`, `gpu`, `full`) is the only tier setting. `editorial.preparation.tier`,
`editorial.reader`, `editorial.laya_audience` and `editorial.detectors_enabled` stop being
settings: the tier sets them, as it already did at runtime. A config, environment variable or
saved setting that still names one logs a warning naming `tier`. They stop being read in 2.0.

A Compose, Kubernetes or Terraform install sets the tier with one variable,
`IMMICH_MEMORIES_DEPLOYMENT_TIER` (`TIER` in the Compose `.env`). It now ranks like any other
environment variable, so it outranks a tier saved in Settings or written in config.yaml. Those are
ignored, with a warning naming the variable, and Settings shows the tier as set by the
environment. If you picked a tier in Settings on a Compose install, that choice stops counting
after the upgrade: set `TIER` in `.env` instead. The variable also takes
`auto`. The shipped deployment files no longer set `IMMICH_MEMORIES_TIER`; if your own files set
both, `IMMICH_MEMORIES_TIER` wins.

`people show --tier` is now `people show --closeness` (inner, recurring, episodic or event).
`--tier` keeps working with a warning until 2.0.

### Settings that left the config

These keys are no longer documented settings. Each one still works through 1.x and logs a warning
when set (the key, never its value); in 2.0 they stop being read. Delete them to use the default.

| Key | What replaces it |
|---|---|
| `editorial.preparation.tier` | `tier` |
| `editorial.reader` | `tier` |
| `editorial.laya_audience` | `tier` |
| `editorial.detectors_enabled` | `tier` |
| `musicgen.hemisphere` | `trips.homebase_latitude`: generated music now reads seasons in your home's hemisphere, like the titles |
| `ace_step.hemisphere` | `trips.homebase_latitude`, as above |
| `automation.upload_to_immich` | `upload.enabled`: one switch for manual and automatic films; the old value is applied to it |
| `automation.album_name` | `upload.album_name`, the same way |
| `server.allow_unauthenticated_lan` | nothing: ignored; without sign-in the UI answers on localhost only |
| `musicgen.num_versions` | `audio.max_regenerations`; ignored |
| `ace_step.num_versions` | `audio.max_regenerations`; ignored |
| `analysis.optimal_clip_duration` | nothing: fixed at 5 s |
| `analysis.min_source_short_side` | nothing: fixed at 1080 px |
| `analysis.max_album_assets` | nothing: fixed at 10,000 per media type |
| `title_screens.title_duration` | nothing: fixed at 3.5 s |
| `title_screens.month_divider_duration` | nothing: fixed at 2 s |
| `title_screens.ending_duration` | nothing: fixed at 7 s |
| `title_screens.month_divider_threshold` | nothing: fixed at 2 clips |
| `llm.preflight_timeout_seconds` | nothing: fixed at 10 s |
| `speech.vad_threshold` | nothing: fixed at 0.25 |
| `speech.min_silence_ms` | nothing: fixed at 200 ms |
| `analysis.live_photo_merge_window_seconds` | nothing: fixed at 10 s |
| `analysis.live_photo_min_clip_seconds` | nothing: fixed at 2.5 s |
| `photos.burst_window_seconds` | nothing: fixed at 300 s |
| `photos.burst_hash_threshold` | nothing: fixed at 8 bits |
| `title_screens.map_move_min_seconds` | nothing: fixed at 6 s |
| `title_screens.map_move_max_seconds` | nothing: fixed at 8 s |
| `audio.music_block_seconds` | nothing: fixed at 240 s |
| `audio.max_music_blocks` | nothing: fixed at 3 |
| `automation.burst_threshold` | nothing: fixed at 2.0 |
| `editorial.preparation.batch_size` | nothing: fixed at 32 |
| `editorial.people.seat_min_pictures` | nothing: fixed at 20 |
| `editorial.people.seat_min_share` | nothing: fixed at 0.05 |
| `editorial.people.big_story_density` | nothing: fixed at 2.0 |
| `editorial.people.big_story_family_share` | nothing: fixed at 0.3 |
| `editorial.laya_audience_threshold` | nothing: the platform's calibrated threshold |
| `editorial.description_model` | nothing: set by the caption provider |
| `editorial.head_versions` | nothing: the shipped producer versions |
| `editorial.pixel_producer_key` | nothing: the shipped producer |

If you set only `automation.upload_to_immich: true`, manual films now upload too: it lands on
`upload.enabled`, which covers both. Delivering only the automatic films is no longer a separate
choice. An `automation.album_name` lands on `upload.album_name`
the same way, unless `upload.album_name` names an album of its own.

The warning reads like this:

```text
Config key photos.burst_hash_threshold is no longer supported: it is internal tuning with no supported use; remove it, it stops being read in 2.0
```

### A birthday film is the year

`--birthday` used to give you the year up to the birthday plus that birthday ±1 day in five
earlier years, mixed into one film. Now it's the year and nothing else, which is what the
automatic birthday films already were. The earlier birthdays are their own film: add
`--years-back N` for the birthday and N earlier ones, each ±1 day, with no year around them. In
the web app the checkbox is **Birthday to birthday**, and the years field under it makes the
birthdays film. `--years-back 5` gives you the five earlier birthdays the old default looked at.

### Scratch and past cuts clean up after themselves

A run killed mid-way (out of memory, a pod restart) used to leave its scratch folder behind for
good, and `editorial-runs/` grew without a limit. Each process now works in a scratch folder of
its own, and the next start removes the ones dead processes left. Leftovers from earlier
releases, including `immich-detector-frames-*` folders at the top of the cache, go once they're
a day old. `editorial-runs/` is held to the new `cache.editorial_runs_max_size_gb` (5 GB by
default): the first run after the upgrade may remove a lot of old attempts, failed and replaced
ones first. Raise the key before upgrading if you want to keep more.

`runs upload` and **Upload to Immich** on the run page now remove the local film once Immich
confirms the upload, as the automation already did. A failed or incomplete upload keeps it.
Copy a film out of the output folder before uploading it if you want a local copy too.

### Views from above count as photographs

On GPU and Full, the document check held views from a summit, a plane or a drone out of every
film as maps. When the frame head is all but certain such a picture is a place, it now counts as
a photograph and can reach a film. Nothing needs re-preparing: the next run reads the facts you
already have. Maps, map boards and map screenshots stay out.

### The web app writes numbers your way

Lengths, sizes and counts in the web app follow the interface language: "1,5 s" and "88,0 Mo" in
French, "1.5 sec" in English (it said "1.5 s" before). Run statuses, the run page's filters and
the sign-in refusals are translated too. A date caption reads "Sonntag, 10." in German instead of
"Sonntag 10", and a Japanese or Chinese title card separates three or more names with its own
comma. Film file names don't change.

### Films in Immich speak the film's language

A film's type tag is in the film's language now, like its story tags: a French month film is
`immich-memories/type/Moments du mois`, not `.../Monthly highlights`. An English film's tags don't
change. A trip film's description starts with its title in ordinary case instead of the title
card's capitals, and a summary names each place once.

`runs render` in another language than the cut was made in, or of a cut made before 1.0.0, uploads
the film with its title as the description and no summary, so the description never mixes two
languages. Cut again to get the summary back.

A long film can wait a while in Immich's queue before Immich reads it, and that read wipes a
description written before it. The upload now waits longer for big files (about four minutes for
a 1 GB film). If the description or tags still didn't stay, the run says so and the delivery
stays pending and the local film is kept. Uploading again (the automatic retry does it for
automatic films) sends the same file, which Immich recognises, and writes the label once more.

### Landscapes drift instead of zooming

A still with nobody in it (a landscape, a building, a plate) used to push 25-35 % into its
centre, the same move a person gets. It now mostly pans gently along its long side at a 12-15 %
zoom, and now and then zooms softly by the same amount. Stills with people move as before.
Re-render a cut to get the new moves.

### Runs remember everyone they were about

A run with several `--person` names used to keep only the first. Runs now keep every name:
`runs list --person Pat` finds a film about Kit and Pat, `runs list` and `runs show` print
`Kit, Pat`, and the web run list names them. The match ignores case. Runs from before the upgrade
keep their one name and are still found under it.

### Three commands exit 1 when they fail

`auto test-notification` exits 1 when nothing was sent, including when notifications are off or
have no URL. `music search` exits 1 when no track matches, `music add` when the mix fails. A
script that ran them and ignored the outcome now sees it.

### Settings shows your config warnings

Settings has a **Checks** section: what loading the config warned about (removed, unknown and
no-longer-supported keys) and the preflight results, the same lines the server log carries.
**Caches** also lists the prepared-source cache, so it can be cleared from there instead of by
deleting `<cache.directory>/prepared-sources` by hand.

### Generated music picks its model

`advanced.ace_step.model_variant` now defaults to `auto`. Local music (`mode: lib`) loads the 4B
XL turbo model on a Mac with 64 GB or more of unified memory or an NVIDIA GPU with 16 GB or more,
and the 2B turbo model below that. If XL fails to load or doesn't fit in the memory free at the
time, the render uses 2B and logs a warning. XL needs about 20 GB more disk for its weights, which
the first render downloads.

A config that already sets `model_variant` keeps that model. To stay on 2B everywhere, set
`model_variant: turbo`.

A single take now leaves its key and time signature to ACE-Step; only a film long enough to need
several takes pins them, so the takes meet in one key. In `api` mode the app asks the server to
skip its planner unless `use_lm: true`, so a server with a planner loaded no longer rewrites the
caption.

### The maximalist Kubernetes overlay holds no Secrets

`deploy/kubernetes/overlays/maximalist` no longer lists `render-worker-secret.yaml` or
`maximalist-secret.yaml`: it builds straight from the checkout, like the base. Create its three
Secrets with `kubectl apply -f`, each from its example, before applying the overlay
([the walkthrough](../reference/cluster-example.md#configure-your-endpoints-and-access)).
Secrets already in the cluster stay where they are. If you apply with `--prune`, create them
separately first, or the prune removes them.

## From 1.0.0-rc.9 to 1.0.0-rc.10

Nothing to migrate by hand. These are the changes you will notice, and the keys that control
them.

### Docker host port

New Docker installs publish host port **22830**; rc.9 and earlier used **8080**. This covers the
release Compose files, the offline Compose example and the Unraid template. An existing install
keeps whatever mapping it has: pulling the new image changes nothing, and an existing Unraid
container keeps its **Extra Parameters**. Only when you replace or regenerate the Compose file do
you need to carry your old `ports:` line over, as [Docker](#docker) below describes. The
container port, native installs and Kubernetes stay on 8080.

### Films in Immich

An uploaded film now gets a description: its title (and subtitle, if it has one) and its
one-line story summary, joined with ` · `. Writing it needs `asset.update` on the key. A key
without it still uploads the film and replaces the earlier render; the run warns and the film has
no description. Add `asset.update`
to the [upload set](../docker.md#the-api-key) if you want descriptions.

Tags for the film's memory type, its years and its named stories (birthdays, visits, trips) are
opt-in. They go under `immich-memories/type/`, `immich-memories/year/` and
`immich-memories/story/`, and need `tag.create` and `tag.asset`:

```yaml
upload:
  film_tags: true
```

Both apply to new uploads and re-renders. Films already in Immich are left as they are.

### Titles

Year, month, season, person, people, birthday, holiday and on-this-day films are titled by
the app, in the film's language: `Kit's birthday · 2026`, `Kit · July 2025`,
`Kit & Pat · 2025`, `Christmas · 2019–2025`. A reader is no longer asked for these, and they get
no subtitle unless you type one. Special days still get the reader's title when one is enabled,
trips do with `--llm-title`, and an album film keeps its album's name. A film for either of two
people now joins their names with `&`, like a film for both.

### Holiday films read every year

A holiday film used to read the five years before it. It now reads every year your library has
around the day, so `generate --holiday` without `--years-back` covers your whole library. Pass
`--years-back 5` to keep the old span. The day itself leads each year, each year gets an even
share of the film, and the title is the holiday's name with the years the cut shows. The timer
only proposes a holiday when the day stands out in your pictures in at least three years.

### Live Photo motion has one floor

`advanced.analysis.live_photo_min_clip_seconds` now applies to every Live Photo clip, a stitch
of nearby Live Photos or one Live Photo's own clip, and its default drops from 3.5 to 2.5
seconds. A clip shorter than that plays as its still: a 1.2-second clip used to slip through as
a burst's fallback and read as half a sentence. A lone Live Photo whose clip lasts 2.5 seconds
and moves still plays. If you set the key yourself, the same value now also gates lone clips;
remove it to take the new default.

### Another 10 GB of cache for re-renders

A re-render now reuses the sources an earlier run prepared (cut segments, photo clips, Live
Photo merges) from `<cache>/prepared-sources`. That cache can grow to 10 GB on the cache volume,
next to the preview and video caches. On a tight volume, lower it or turn it off with `0`:

```yaml
advanced:
  analysis:
    prepared_source_cache_max_size_gb: 5
```

It is also off when `cache.video_cache_enabled` is false.

### The preview cache holds a whole library

`cache.thumbnail_cache_max_size_mb` now defaults to 30 GB (was 10 GB). A year, a lifetime or a
captioning pass reads a preview of every picture in scope, about 0.32 MB each, so 10 GB evicted
previews a library over about 30,000 pictures still needed, and the next film downloaded and
captioned them again. If you set the key yourself, your value still wins. Plan disk as about
25 GB plus 0.35 GB per 1,000 pictures and videos.

On Kubernetes the base cache claim (and Terraform's `cache_storage_size`) goes from 30Gi to
60Gi. Applying the new manifests asks the existing claim to grow: that works only when its
StorageClass allows volume expansion. If yours doesn't, keep 30Gi with a patch in your overlay
and lower the caps to fit, for example `thumbnail_cache_max_size_mb: 15000`.

### Generated music

`audio.music_block_seconds` now defaults to 240 (was 120), so a film up to four minutes gets one
ACE-Step take instead of several joined ones. Longer films get takes that share one style, tempo
and key, joined on a bar line. When the app picks the style itself, it picks acoustic,
electronic or piano; jazz, rock, orchestral and metal play only when you ask for them. If you set
`music_block_seconds` yourself, your value still wins.

### Settings the web UI no longer changes

The render worker's address and token, the local model server and the paths to programs and
model files (`render.worker_base_url`, `render.worker_token`, `llm.local_server`,
`triage.encoder`, `free_text.wordnet`, `editorial.laya_checkpoint` and the three
`editorial.preparation` paths) are now read only from `config.yaml` or the environment. If you
saved one of them from the Settings page on an earlier release, the app ignores it at startup and
logs a warning naming the key: move the value into `config.yaml` or the environment and restart.
[Network security](../network-security.md#settings-only-the-operator-sets) says why.

### New opt-in key

`advanced.analysis.forwarded_copies_when_short` (default `false`) lets forwarded copies and saved
images fill a week, month or year that has no camera picture. A copy is dated when it was
received, so an old photo shared again can land in the wrong year.

## Security changes in 1.0

Five behaviours changed for security, without a deprecation period. Each one has a fix.

- **Credentials in `immich.url` stop startup.** Remove the username and password from the URL
  and use `immich.api_key`. This also applies to each account's URL under `immich.accounts`. If a
  reverse proxy requires URL credentials, give the app a private route to Immich that accepts
  its API key.
- **`auth.public_url` restricts accepted hosts.** With authentication enabled, requests are
  accepted only for its hostname, localhost and the entries in `server.allowed_hosts`. Any
  other host gets HTTP 421. If you also open the app by a LAN IP or another hostname, add those
  addresses to `advanced.server.allowed_hosts` before upgrading.
- **`/health` hides details without a session.** With authentication enabled, `/health` and
  `/health/ready` keep their status codes and JSON fields, but return `null` for
  `configuration`, `immich` and `immich_reachable` unless the request has a valid session. Use
  the HTTP status for probes; sign in to read the detailed diagnosis.
- **Some settings are config-file or environment only.** `render.worker_base_url`,
  `render.worker_token`, `llm.local_server`, `triage.encoder`, `free_text.wordnet`,
  `editorial.laya_checkpoint`, `editorial.preparation.detector_python`,
  `editorial.preparation.detector_cache_dir` and `editorial.preparation.marqo_onnx` can no longer
  be saved from Settings or the web API. Values you saved there earlier are ignored at load, with
  a warning that names the keys. Move each one to `config.yaml` (under
  `advanced:` where the [reference](../../reference/config-reference.md) puts it) or to its
  `IMMICH_MEMORIES_<SECTION>__<FIELD>` environment variable.
- **Request bodies are capped at 4 MiB.** Every HTTP request, including reads and sign-in pages,
  accepts a body up to 4 MiB and larger ones return HTTP 413. The soundtrack upload route keeps
  its separate 64 MiB file limit.

## HTTP monitoring

For custom Kubernetes or Terraform deployments, set liveness to `/health/live` and readiness
to `/health/ready` before applying the new image. Both accept the pod IP in the probe's `Host`
header. The shipped manifests already use these paths.

A probe still using `/health` can receive HTTP 421 when `auth.public_url` or
`server.allowed_hosts` restricts the accepted hosts. This can keep the pod unready or make
Kubernetes restart it. Change the probe paths in the manifests or Terraform that own the
deployment. `/health` is a compatibility endpoint, not a readiness check.

## New automatic films

The daily timer (`auto`) now looks for five more kinds of film. They are on by default, so an
install with the timer starts getting them. Each has a key under `advanced.automation` that
turns it off:

| Film | Key |
|---|---|
| The season that just ended | `detect_seasons` |
| A holiday across the years | `detect_holidays` |
| A new or grown Immich album | `detect_albums` |
| Last month's film of each person close to you | `detect_person_monthly` |
| Months of this year and last that never got a film | `backfill_months` |

```yaml
advanced:
  automation:
    detect_seasons: false
    detect_holidays: false
    detect_albums: false
    detect_person_monthly: false
    backfill_months: false
```

See [automation](../../make/automate.md) for what each one proposes.

## Temporary working files

Keep cache and output directories on mounted storage with free space. At startup the app and
workers put Python and child-process temporary files in a private `scratch` directory on their
configured storage. An existing directory with group or other access is refused. Setting
`TMPDIR` does not override this startup choice.

See [temporary working files](./storage-backups.md#temporary-working-files) for the locations
and interrupted-run recovery.

## Job progress files

The web job directory becomes accessible only to the app account when the web server opens it.
Existing job history is kept, including older progress files. The parent cache folder keeps its
permissions.

Files written by `runs render --progress-file` are readable only by the writing account (0600).
Run a file watcher as that account. Old progress files outside the web job directory keep their
permissions until rewritten; restrict them yourself if they contain private output paths.

## API key permissions

Existing keys with **All** permissions continue to work. Preflight now warns about their broad
access; replace them with the [documented read set](../docker.md#the-api-key), adding upload
rights only when needed. Run `immich-memories config test` after changing a key.

Missing read permissions stop a cut before it starts. Missing upload or tagging permissions
keep the completed film locally with a download option and a specific delivery message.
Without `asset.delete`, previous versions remain in Immich. Partner keys need only read rights.

## Docker

Back up while the old release is still running:

```bash
docker compose exec immich-memories immich-memories store backup
docker compose cp immich-memories:/home/immich/.immich-memories/backups ./backups
```

Keep that backup and manifest. Download the new release's Compose assets and set
`IMMICH_MEMORIES_VERSION=X.Y.Z` in `.env`, without the `v` prefix. That one value selects matching
app, inference and standalone worker images; the CUDA file adds the inference CUDA suffix.
Keep your chosen `COMPOSE_FILE`, credentials and saved Settings. If you use a single-file export,
regenerate it with the new version and preserve its private settings key.

**Keep your existing host port when replacing or regenerating Compose files.** From 1.0.0-rc.10
on, the release Compose files and the Unraid template publish host port **22830**; 1.0.0-rc.9 and
earlier published **8080**. Copy your current `ports:` mapping into the new file before starting
it, including the bind address. For example, an existing `127.0.0.1:8080:8080` can stay exactly
that. The last number is the container port, which remains 8080. An image-only upgrade keeps the
existing mapping, and an existing Unraid container keeps its **Extra Parameters**.

If you choose to move an existing install to 22830, update browser bookmarks and any host-based
reverse proxy, tunnel or firewall rule that names the old port. Proxies that connect directly
to the app container still use 8080. Then upgrade:

```bash
docker compose pull
docker compose up -d
docker compose exec immich-memories immich-memories models fetch
docker compose exec immich-memories immich-memories preflight
```

Images tagged `nightly` or `nightly-YYYYMMDD` are daily builds of `main` for testing what is
coming. They are not for production: pin a release version.

Config and films survive a recreate.
`models fetch` checks the new release's pins and downloads only changed files.

## uv / pip

Back up before changing the installed package:

```bash
immich-memories store backup
```

The native install pins a version. `uv tool upgrade` keeps that pin, so replace it by running the
current package command for your platform:

<InstallationFiles kind="native" />

Keep any extras you added: on Apple Silicon with OIDC, change `[all-mac]` to `[all-mac,auth]` and
retain `--with laya-mlx`. This updates the app environment and leaves its configuration and store
in place. See [uv's version-constraint rule](https://docs.astral.sh/uv/guides/tools/#upgrading-tools).

For pip, run `python -m pip install --upgrade` inside the app's virtual environment with the same
quoted package and version specification shown above. Keep the same extras; Apple Silicon GPU/Full
also needs `laya-mlx` in that environment.

Then verify the new model pins and installation:

```bash
immich-memories models fetch
immich-memories preflight
```

## Kubernetes and Terraform

Back up, change the pinned image tag, apply, then run `models fetch` and `preflight` in the app
container. The base init container skips fetching when its required paths are present, so changed
pins need the explicit fetch. The generated GPU setup runs `models fetch --detectors --laya`
whenever its model init container runs, verifying existing artifact digests.
See [Kubernetes upgrades](../reference/kubernetes-operations.md#upgrading-and-rollback) or
[Terraform upgrades](../terraform.md#upgrading).

### Kubernetes scratch permissions

Set this pod-level policy in custom manifests too (Terraform: `fs_group_change_policy`):

```yaml
securityContext:
  fsGroup: 1000
  fsGroupChangePolicy: OnRootMismatch
```

With the default `Always` policy, every pod start can widen the `scratch` directory in the cache
from 0700 to 2770. The app narrows it back to 0700 at startup when it is a real directory owned by
its own user, so nothing needs repairing by hand. It holds only throwaway temp files.

A symlinked `scratch`, or one owned by another user, is still refused with
`Runtime scratch storage must be a private directory.` Check that the mounted path is a plain
directory owned by UID 1000 (`ls -ld <cache>/scratch`), and remove or rename it if it is not. The
inference service uses `<inference cache>/scratch` and the render worker
`<worker directory>/scratch`.

A CSI driver that handles `VOLUME_MOUNT_GROUP` itself controls the ownership changes. See
[Kubernetes volume ownership rules](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/#configure-volume-permission-and-ownership-change-policy-for-pods).

## Upgrading Immich from v2 to v3

Leave version detection on auto:

```yaml
immich:
  api_version: auto
```

After upgrading Immich:

```bash
immich-memories config test
```

This read-only check prints the resolved v2/v3 contract. Overrides are for troubleshooting a
proxy, not an upgrade step. Originals are unchanged.

### Immich 3.3

- **Country names.** Immich 3.3 stores GeoNames' English country names ("The Netherlands",
  "Turkey", "Cabo Verde"). The app reads those and the earlier names alike, so titles and captions
  still translate the country.
- **Stacks.** Add `stack.read` to the key if you want a stack (an edit and its original, a burst)
  to play as its top picture. It is optional: without it the run logs one warning per account and
  treats every stacked picture as its own candidate.
- **Native people sharing** is tested on 3.3.3. It also accepts 3.3.0-rc.1, later
  3.3.0 release candidates and every 3.3 release. See [A second Immich account](../multi-account.mdx).

## Scheduled runs

A schedule set up with `auto install` before 1.0 has `--cooldown 24` written into its command, which
overrides `automation.cooldown_hours`. Rerun `immich-memories auto install` so the scheduler uses
`automation.cooldown_hours`, then run the activation command it prints.

## Config compatibility

Unknown fields inside a known section are ignored; invalid values or unknown top-level sections
fail startup. A renamed setting can stop taking effect, so check the release notes. A removed key
is dropped with a warning at startup that names it and says what to do, for example:

```text
Ignoring config keys that no longer exist in config.yaml; delete them to silence this:
  audio.music_volume_db: nothing read it; remove it from your config
  defaults.output_orientation: the CLI picks the orientation; remove it from your config
```

Delete the key once you've read why.

The low-end tier is `basic`. A `tier: nas` in YAML, `IMMICH_MEMORIES_TIER=nas`,
`IMMICH_MEMORIES_DEPLOYMENT_TIER=nas` or a saved Settings value of `nas` stops startup with
`tier 'nas' is now called 'basic': set tier: basic`. Change the value to `basic`.

The reader only runs with `advanced.llm.enabled: true`. A config that sets `advanced.llm.base_url`,
`model` or another reader field without it keeps the reader off: model titles, music mood and model
selection stay off, startup logs a warning naming the fields it found (never their values), and
`preflight` reports **Reader configured but disabled**. Add `enabled: true` under `advanced.llm`.
See [enabling a reader](../config-file.md#enabling-a-reader).

The store upgrades its schema when opened. Keep a backup and its manifest from before an update;
if you roll back the app, restore the matching backup rather than downgrading a live schema.
Keep the app, inference image and render worker on matching version tags.

## Rollback

Restore the backup taken before upgrading if the newer release migrated the store.
Stop the app before restoring. [Container restore](./storage-backups.md#restore)
uses a one-off process, not `exec` in the running app.

For Docker, use this order. The backup and its manifest must be together on the mounted config
volume. Replace the example backup name with yours (`.dump` for PostgreSQL):

```bash
docker compose stop immich-memories
# Set IMMICH_MEMORIES_VERSION in .env to the old release (no v prefix).
# For single-file/custom installs, set matching app, inference and worker image tags.
docker compose pull
docker compose run --rm immich-memories immich-memories store restore \
  --from /home/immich/.immich-memories/backups/store-20260930T090000Z.db --force
docker compose up -d
docker compose exec immich-memories immich-memories preflight
```

Python:

```bash
uv tool install --force --python 3.12 "immich-memories[all]==X.Y.Z"
```

Kubernetes/Terraform: restore the old image tag and apply, then restore the old store backup with
that release. Schema downgrades can drop tables and rows; the backup is the rollback.

## Inspecting the store before an upgrade

`store status`, `store backup`, `config show` and `preflight` read the existing schema without
upgrading it, including saved settings. A revision mismatch reports the actual and expected
schema. Back up first; `ui`, `generate`, `auto` and the explicit `store migrate` command upgrade
the configured store before writing.
