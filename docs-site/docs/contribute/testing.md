---
title: Testing Guide
---

# Testing guide

Start with unit tests, then run the checks for the boundaries your change touches: optional backends, real Immich, the store or the browser. `make help` lists common suites; the Makefile contains all per-suite targets.

| Tier | Command | What it needs |
|------|---------|---------------|
| Unit | `make test` | FFmpeg on the `PATH`: a handful of unit tests encode real media |
| Extras | `make test-extras` | The torch-family extras (demucs/editorial). CI's extras job installs neither, so a green CI run does not prove the torch paths ran |
| Integration | `make test-integration` | FFmpeg, an Immich server in `~/.immich-memories/config.yaml`, and at least two clips of 15 seconds or less in that library |
| Store | `make test-store-sqlite`, `make test-store` | `tests/store/` on SQLite, then on PostgreSQL too. `make test-store` starts a throwaway `postgres:16` in Docker unless `IMMICH_MEMORIES_TEST_DATABASE_URL` names one; each test gets its own schema. `make test` runs the SQLite half |
| Real-Immich gate | `make test-immich-gate IMMICH_GATE_VERSION=v2` (or `v3`), plus `IMMICH_GATE_DATABASE=postgresql` for the store on PostgreSQL | Docker and FFmpeg. It starts its own Immich and fixture library, and fails when Immich does not come up |
| E2E | `make e2e` (`make e2e-full` for the generation flow) | `make playwright-install`; no Immich, it runs against a fake server |
| Launch check | `make launch-check-ci`, `make launch-check-ci-postgres` | The required E2E set. The PostgreSQL one gives each launch its own schema in `IMMICH_MEMORIES_E2E_DATABASE_URL`, or starts a throwaway `postgres:16` when that is unset |
| Container | `make test-container` (`CONTAINER_E2E_DATABASE=postgresql` for PostgreSQL) | Docker. Builds the image and runs it; see below |

`make test-fast` excludes slow, integration, e2e and container tests; the full suite is `make test`.
Integration suites skip rather than fail when their services aren't there, unless `REQUIRE_IMMICH=1` (the gate below sets it). The Makefile lists the per-suite targets. Three suites are outside `make test-integration`: `cli`, which
re-runs the pipeline `pipeline` already covers and is the slowest in the tree; `audio`, which wants
the demucs and ACE-Step packages; and `automation`, which has no dedicated make target. For that
suite only, use `uv run pytest -m integration tests/integration/automation`. The marker override
is required: pytest's default options exclude integration tests. This command reads your configured
Immich library and uses your real app home, so it needs the same setup as the other integration suites.

## The real-Immich gate

Unit tests talk to a patched HTTP client and the integration suites skip when no Immich is
configured, so neither proves the product still speaks to a real server. The `Immich Gate` check
does, for both majors when the change scope calls for it (see [CI](./ci.md)):

1. `make immich-gate-up` starts Immich 3.3.0, Postgres and Valkey from
   `tests/integration/immich_gate/docker-compose.yml`. Every image is pinned by digest, there is no
   machine-learning container, and Postgres and the uploads live on tmpfs, so `make immich-gate-down`
   leaves no volume behind.
2. `seed.py` signs up an admin, uploads the June 2024 CC0 fixture month (133 pictures, 13 of them
   videos, with EXIF camera and capture time), places them, tags three made-up people by hand,
   files the story albums, and adds 1,010 tiny pictures in one album so reads have to go past
   Immich's 1,000-item search page. Then it writes a rules-tier config under `.immich-gate/`.
   There is no hosted reader or music API, but local detector models and WordNet still need
   download/cache preparation; this is not a guarantee of no model or network use.
3. The tests in `tests/integration/immich_gate/` run with `REQUIRE_IMMICH=1`, which turns
   `requires_immich` and `make_immich_client()` from a skip into a failure.

| Test | What it proves on each major |
|------|------------------------------|
| connect | the key works and the client resolves the API version the server runs |
| fixture month | every video and still of a date range comes back, stills with their camera, videos with their place |
| paging | a year and an album of 1,010 pictures read whole |
| people | hand-tagged faces scope the videos per person |
| albums | story albums list and resolve by name with their counts |
| upload | a re-rendered film lands in its album and trashes the earlier copy (v2 by device identity, v3 by the provenance tag) |
| generate | `generate --memory-type monthly_highlights --no-render` on the rules tier picks a cut from the fixture month |
| store | a `people scan` and a `pictures never-use` read back from the store, a second `prepare` of the month changes no banked fact, and a rendered film is in the run history with its phases |

Choose the server with `IMMICH_GATE_VERSION=v2` (2.7.5), `v32` (3.2.2) or `v3` (3.3.0, the
default). Locally, each version can run on either store backend. CI runs all three with SQLite
for applicable changes and adds PostgreSQL when the store changes.
`IMMICH_GATE_DATABASE=postgresql` starts a throwaway `postgres:16` for the run, in CI too (a job
service would not survive the workflow's Docker daemon restart), unless
`IMMICH_GATE_DATABASE_URL` names a server. The runs get the store through `IMMICH_MEMORIES_DATABASE_URL`, the same variable a
deployment uses.

The gate is deliberately small and stable. Wider real-Immich coverage stays in the other
integration folders. `IMMICH_GATE_KEEP=1` leaves the stack running after the tests; a failed run
writes the server logs to `.immich-gate/immich-<version>.log` (CI uploads them as an artifact).

In CI the pinned images come from the Actions cache, not the registries: one `docker save` tarball per
major, keyed on the exact refs. `make immich-gate-fetch` loads it, and pulls whatever it lacks with
three attempts of three minutes each; `make immich-gate-save` writes it back after a cold run. A
registry that stalls then costs one attempt instead of the whole job, and an image that never
arrives still fails the gate.

## The container suite

CI builds the Docker image for changes that affect it; `make test-container` is what runs it. It builds the
image with the `editorial` extra (`CONTAINER_E2E_BUILD=0` reuses one already built), then drives
the repo's own `docker-compose.yml` from `tests/container/`:

1. **Import.** A synthetic file-backed volume under `~/.immich-memories`
   (`tests/store/legacy_home.py`: people, runs, automation attempts, owner decisions, model
   answers, banks, all synthetic) goes on the config volume before the new image first starts.
   The first start imports it, and `store import --verify` finds every fixture record.
2. **Store commands.** `store status`, `store backup`, and `store restore --force` into a scratch
   store inside the container, with every table's count equal. On PostgreSQL that is the image's
   own `pg_dump` and `pg_restore` against a `postgres:16` server, restoring into a second database
   on it: a restore renames the backup's schema, so it cannot share a database with the schema it
   came from.
3. **Trigger API.** The app runs with a trigger token and uploads off. The Kubernetes CronJob's
   own pinned curl image sends its exact `POST /api/trigger` from another container on the
   network: the answer is `accepted` and the attempt lands in the store's automation history. No
   Immich answers, so the attempt is recorded as failed, which is the point: the record is what
   is under test. A wrong token gets a 401.

`CONTAINER_E2E_DATABASE=postgresql` switches on the compose file's commented PostgreSQL example,
exactly as a user would uncomment it, so that example is tested too. The synthetic fixture covers every file the importer reads without requiring a live library or model endpoint.

## Coverage and diff-cover

CI uploads unit coverage to Codecov under the `unittests` flag and the self-hosted GPU runner
uploads the integration suites under `integration-linux`; Codecov merges the two. The per-suite
XMLs that `make test-integration` writes locally (`tests/*-coverage.xml`, `tests/*-junit.xml`) are
gitignored.

A PR needs 80% coverage on the lines it changes. The gate skips itself with a warning when the diff
is under 10 source lines or over 1000, and `analysis/apple_vision*.py` is excluded outright.

Before checking, CI runs the FFmpeg-only integration suites covering the paths your diff touches,
and only those, then merges their coverage into the diff-cover run. So code reachable only through
FFmpeg is covered for you. To reproduce what CI will see:

```bash
make integration-coverage-for-diff   # runs only the suites your diff touches
make diff-cover-local                # merges them with unit coverage, same as CI
```

If diff-cover still fails after that, the uncovered lines are not reachable from an integration
suite and do need unit tests. Subprocess boundaries can be stubbed rather than run for real:
`tests/test_ffmpeg_pipe.py` shows the pattern.

If you changed `processing/`, `analysis/`, `titles/` or `generate.py`, run the matching integration
suite locally before pushing, so you catch FFmpeg regressions before the GPU runner does.

## Writing integration tests

1. **Mock WRITES, not READS**: real Immich for fetching assets, real FFmpeg for encoding. Only mock upload and mutation.
2. **Use short clips**: 15 seconds or less, 2-3 per test. Full pipeline tests should finish in under 2 minutes.
3. **Skip gracefully**: use the `requires_ffmpeg` and `requires_immich` markers.
4. **Assert the contract**: check valid output and duration, and use exact timing or content assertions when deterministic (for example, a certified frame endpoint).
5. **Log during tests**: `make test-integration` shows live logs (`--log-cli-level=INFO`).

```python
@requires_immich
class TestMyFeature:
    def test_real_pipeline(self, immich_short_clips, tmp_path):
        clips, config, client = immich_short_clips
        config.title_screens.enabled = False  # Skip for speed

        params = GenerationParams(
            clips=clips[:2],
            output_path=tmp_path / "test.mp4",
            config=config,
            client=client,
            upload_enabled=False,  # NO WRITES
        )

        result = generate_memory(params)
        assert result.exists()
        assert get_duration(ffprobe_json(result)) > 0
```

## Failed or cancelled CI

Read the failed step. An assertion failure names a test; exit 137 can mean the runner ran out of memory. A cancelled test job did not finish and is not a pass. Check whether a newer run superseded it before rerunning failed jobs.

```bash
gh run list --branch YOUR_BRANCH
gh run rerun RUN_ID --failed
```

Wait until the run finishes before requesting a rerun. If the same job repeatedly runs out of memory, investigate resource use instead of treating retries as validation.

The [CI guide](./ci.md) describes change scope, matrix jobs and required rollups.

## Hardware encoders are absent on CI

`render_single_photo` chooses its encoder from the encoding plan and verified hardware
capabilities. The `zscale` filter controls colour conversion; its presence does not prove a
hardware encoder works. For a test that needs real FFmpeg output on the CPU, pass
`capabilities=HWAccelCapabilities()` to `render_single_photo`. To exercise a caller that probes
the hardware itself, replace that probe:

```python
from immich_memories.processing.hardware import HWAccelCapabilities

# WHY: the test needs software encoding regardless of the machine running it.
monkeypatch.setattr(
    "immich_memories.processing.hardware.detect_hardware_acceleration",
    lambda *args, **kwargs: HWAccelCapabilities(),
)
```

Keep the real filter checks when the test verifies HDR or colour conversion.

## Native Immich sharing

After `make dev`, run either pinned native-identity gate:

```bash
make test-native-sharing NATIVE_GATE_VERSION=v32-sharing
make test-native-sharing NATIVE_GATE_VERSION=v33-sharing
```

Each starts an isolated Immich, seeds the CC0 household library, runs the checks and removes
its containers. `NATIVE_GATE_PORT` defaults to `2304`. Disposable keys stay under the ignored
`.immich-gate` directory. Never publish its state file.

The gates cover the partner-only person episode, selected-owner scope, timeline changes,
favourites on absorbed copies, read-only keys and upstream person merges. The 3.3 gate also
checks people-sharing roles and revocation. The 3.2 fixture connects manually assigned faces
through the disposable database; it does not test recognition accuracy. Production fetching
never writes cluster or sharing state. The pinned versions are 3.2.4 and 3.3.0.
