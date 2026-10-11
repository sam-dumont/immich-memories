---
paths:
  - "tests/**"
  - "src/**"
  - "web/**"
---

# Testing

Work test-first in vertical slices: one failing test for the next behaviour, the minimal code that
passes it, a refactor once it's green, then the next slice. Tests check behaviour through public
interfaces so they survive internal refactors. `.agents/skills/tdd/SKILL.md` has the full method.

While iterating, run the tests you're touching (`uv run pytest tests/<files>`). The pre-commit hook
runs the whole suite once, when you commit.

## Test what users get

Unit tests against fakes have passed while advertised features were broken: a flag that never
reached the cut, an error that printed every secret, a fake client that accepted arguments the real
one rejected. To catch that class of bug:

- When a fix changes user-visible behaviour, test the real output: the cut, the rendered file, the
  printed message.
- Build fakes of the Immich client with `create_autospec` from the real client, so they reject what
  it rejects (`tests/immich_fakes.py`: `fake_immich_client()`, and `ImmichWire` for httpx fakes).
- A feature the docs advertise gets a feature test on the fixture library (epic #2128 tracks the
  build-out).

## Mocks

- Mock at most three boundaries in one test; needing more means the code under test has too many
  dependencies.
- Give each mock a `# WHY:` comment naming the boundary it replaces.
- Mock writes (uploads, database mutations) and use real reads (Immich fixtures, FFmpeg).
- Spend tests on behaviour, not on dataclass fields, property getters or Python arithmetic.

## Sealed runs

The suite moves `HOME` and the store to a throwaway directory only when its `-m` expression excludes
integration tests; the default addopts do. Run pytest with the default addopts or through a `make`
target. An `-m` that selects integration keeps the real home, which is right only for the
integration targets. A test that writes under `Path.home()` asserts it is sealed before writing.

## Parallel runs

The unit suite, the FFmpeg-only integration folders and the store suite run on pytest-xdist workers
(`TEST_WORKERS`: `auto` on CI, half the cores locally; `0` runs in one process). Each worker has its
own sealed home, store and fake services, and the order is whatever the scheduler picks. A test owns
the state it asserts on: don't count uploads, runs or log lines another test may have left, restore
module globals and logger levels you change, and swap imports with `monkeypatch.setitem(sys.modules,
...)`, not `patch.dict(sys.modules, ...)`. A test that passes only after another one gets fixed,
never run in series.

## Tiers

| Tier | Command | Needs |
|---|---|---|
| Unit | `make test` (`TEST_WORKERS=N`) | FFmpeg for media fixtures |
| Extras (torch family) | `make test-extras` | torch, demucs, face |
| Integration | `make test-integration` or a folder target | FFmpeg + Immich |
| Store | `make test-store` | Docker (postgres:16) |
| Launch | `make launch-check-ci`, `make launch-check-ci-postgres` | Playwright + FFmpeg (+ Docker) |
| Feature | `make test-features`, `make feature-check` | FFmpeg + LFS fixture library |
| Real Immich gate | `make test-immich-gate` | Docker + FFmpeg |
| Built image | `make test-container` | Docker |
| Web client | `make e2e` | Playwright |

An FFmpeg pipeline change gets an integration test under `tests/integration/` and a run of that
folder's target (`assembly`, `audio`, `audio_mixing`, `titles`, `photos`, `processing`, `pipeline`,
`cli`, `live_photos`).

Coverage: 65% on core code (`fail_under`) and 80% on changed lines (`make diff-cover`). The Svelte
client in `web/` is covered by the Playwright suite; its API by the unit tests of
`src/immich_memories/web/`.
