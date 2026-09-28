---
title: Testing Guide
---

# Testing guide

Two suites: fast unit tests that run everywhere, and integration and E2E tests that need real
services. `uv run pytest tests/ --collect-only -q` prints the current split.

| Tier | Command | What it needs |
|------|---------|---------------|
| Unit | `make test` | FFmpeg on the `PATH`: a handful of unit tests encode real media |
| Extras | `make test-extras` | The torch-family extras (demucs/editorial). CI's extras job installs neither, so a green CI run does not prove the torch paths ran |
| Integration | `make test-integration` | FFmpeg, an Immich server in `~/.immich-memories/config.yaml`, and at least two clips under 30s in that library |
| Store | `make test-store-sqlite`, `make test-store` | `tests/store/` on SQLite, then on PostgreSQL too. `make test-store` starts a throwaway `postgres:16` in Docker unless `IMMICH_MEMORIES_TEST_DATABASE_URL` names one; each test gets its own schema. `make test` runs the SQLite half |
| Real-Immich gate | `make test-immich-gate IMMICH_GATE_VERSION=v2` (or `v3`), plus `IMMICH_GATE_DATABASE=postgresql` for the store on PostgreSQL | Docker and FFmpeg. It starts its own Immich and fixture library, and fails when Immich does not come up |
| E2E | `make e2e` (`make e2e-full` for the generation flow) | `make playwright-install`; no Immich, it runs against a fake server |
| Launch check | `make launch-check-ci`, `make launch-check-ci-postgres` | The required E2E set. The PostgreSQL one gives each launch its own schema in `IMMICH_MEMORIES_E2E_DATABASE_URL`, or starts a throwaway `postgres:16` when that is unset |
| Container | `make test-container` (`CONTAINER_E2E_DATABASE=postgresql` for PostgreSQL) | Docker. Builds the image and runs it; see below |

`make test` takes about 3 minutes on an M-series Mac; `make test-fast` skips the slow ones.
Integration suites skip rather than fail when their services aren't there, unless `REQUIRE_IMMICH=1` (the gate below sets it). `make help` lists every
per-suite target with its runtime. Three suites are outside `make test-integration`: `cli`, which
re-runs the pipeline `pipeline` already covers and is the slowest in the tree; `audio`, which wants
the demucs and ACE-Step packages; and `automation`, which has no target at all (run
`pytest tests/integration/automation`).

## The real-Immich gate

Unit tests talk to a patched HTTP client and the integration suites skip when no Immich is
configured, so neither proves the product still speaks to a real server. The `Immich Gate` check
does, on every PR, for both majors:

1. `make immich-gate-up` starts Immich (v2.7.5 or v3.2.2), Postgres and Valkey from
   `tests/integration/immich_gate/docker-compose.yml`. Every image is pinned by digest, there is no
   machine-learning container, and Postgres and the uploads live on tmpfs, so `make immich-gate-down`
   leaves no volume behind.
2. `seed.py` signs up an admin, uploads the June 2024 CC0 fixture month (133 pictures, 13 of them
   videos, with EXIF camera and capture time), places them, tags three made-up people by hand,
   files the story albums, and adds 1,010 tiny pictures in one album so reads have to go past
   Immich's 1,000-item search page. Then it writes a rules-tier config (no model, no network
   beyond this Immich) under `.immich-gate/`.
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

Every test runs twice per major: the app's store on SQLite, and on PostgreSQL. CI gives the
PostgreSQL legs a `postgres:16` service; locally `IMMICH_GATE_DATABASE=postgresql` starts a
throwaway one. The runs get the store through `IMMICH_MEMORIES_DATABASE_URL`, the same variable a
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

CI builds the Docker image on every PR; `make test-container` is what runs it. It builds the
image with the `editorial` extra (`CONTAINER_E2E_BUILD=0` reuses one already built), then drives
the repo's own `docker-compose.yml` from `tests/container/`:

1. **Upgrade.** A volume laid out the way a pre-store install left `~/.immich-memories`
   (`tests/store/legacy_home.py`: people, runs, automation attempts, owner decisions, model
   answers, banks, all synthetic) goes on the config volume before the new image first starts.
   The first start imports it, and `store import --verify` finds every legacy record.
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
exactly as a user would uncomment it, so that example is tested too. Why the volume is written by
the fixture and not by the previous release's image: that image cannot write owner decisions or
model answers without a live Immich and a model endpoint, and the fixture covers every legacy
file the import reads.

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
2. **Use short clips**: under 30s, 2-3 per test. Full pipeline tests should finish in under 2 minutes.
3. **Skip gracefully**: use the `requires_ffmpeg` and `requires_immich` markers.
4. **Assert properties, not content**: "valid video exists" and "duration > 0", not exact pixels or durations. Content is non-deterministic.
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

## When CI fails but nothing failed

A red `Test (Python 3.12, ubuntu-latest)` often means the runner was reclaimed mid-suite, not that
your code broke on Linux. A cancelled job is a job that did not run, so merging while one is
outstanding means merging on the strength of whichever jobs happened to survive.
`TestPhotoPlaceCaption` reached `main` broken and stayed there through two PRs that way: red and
ignored once, reclaimed and never run the second time.

Read the step, not the log:

```bash
gh api repos/<owner>/<repo>/actions/jobs/<job-id> \
  -q '.steps[] | select(.conclusion=="cancelled" or .conclusion=="failure") | "\(.name) -> \(.conclusion)"'
```

`Run tests with coverage -> cancelled` with everything downstream `skipped` is a runner that died.
No assertion ever ran, which is why `gh run view --log-failed` returns nothing: an empty failure
log is evidence, not a broken tool. Swap the query for `.started_at` and `.completed_at` to see how
far it got. Four minutes against a suite that takes eleven means it never finished.

The matrix is a control group: one cell red with its siblings green on the same OS points at a dead
runner, every Linux cell red with macOS green at a real platform difference. It is a hint, not the
verdict, because two cells can be reclaimed at once under memory pressure. The log decides:
`FAILED` lines mean a real failure, `Error 137` after a run of `PASSED` lines means the runner was
killed. One photo-caption test failed with `Error 137` on Python 3.12 and passed on 3.11 and 3.13
in the same run on the same image. The test was correct: it was the slowest thing running when the
runner was killed.

The OOM lands on whatever is running, which skews toward the slow tests. Two have been trimmed for
that reason rather than because they were wrong: the loudnorm fixtures (thirty FFmpeg calls to one)
and the photo-caption test (120 encoded frames to 30, to assert one string). If a unit test renders
video to check metadata, shrink the render.

The `CI Success` gate tolerates `cancelled`, because the concurrency group cancels superseded runs
and a runner death still produces `conclusion=failure` on the job (`make` returns 137). Check
`gh run list --branch <branch>` to confirm a newer run covered the cancelled one.

`gh run rerun <run-id> --failed` is rejected while any job in the run is still in progress; the
error message about a broken workflow file is misleading. Wait for the run to complete. If the same
cell is reclaimed three times, treat it as a resource problem rather than luck.

## Hardware encoders are absent on CI

`render_single_photo` picks its encoder from `check_zscale_available()`: with zscale it uses
`hevc_videotoolbox`, without it `libx264`. VideoToolbox writes no file inside CI's macOS VM, and
the function returns `None` when encoding produces nothing, so the failure surfaces as whatever the
test asserted next, not as an encoder error. Any unit test that reaches the photo encoder needs the
software path forced:

```python
monkeypatch.setattr(
    "immich_memories.processing.hdr_utilities.check_zscale_available", lambda: False
)
```

It passes on a real Mac either way, which is what makes this one easy to merge and hard to notice.
