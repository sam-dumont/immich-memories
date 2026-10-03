---
title: Architecture
sidebar_label: Architecture
---

import DeploymentDiagram from '@site/src/components/DeploymentDiagram';

# Codebase architecture

How the code is organized and where to make changes.

## Runtime boundaries

The web UI and terminal use the same CLI workflow: **choose a cut → render it → optionally upload it**. A render consumes the chosen cut; it does not choose footage again. The store keeps reusable facts, settings and history; per-attempt records explain the decisions in one cut.

## Data and service boundaries

Explore the deployment and processing phase below. Select a service for its data and runtime responsibilities. These are service boundaries, not a promise about GPU placement.

<DeploymentDiagram chooseTopology />

The text reader can be an app-owned local process or an API server. Captioning is a separate role; explicitly enabling LLM captions sends pictures to that configured model. A render worker additionally receives the chosen cut and Immich key, then fetches originals. Keep these services inside the network boundaries described in [Privacy](../run/privacy.md).

## Composition over inheritance

The four main orchestrators compose smaller service objects through constructor injection. The
lifecycle a run reports is the `OperationalPhase` enum in `operations/phases.py` (discovery →
download → analysis → selection → render → music → delivery → complete), and it spans two entry
points. Selection runs first: `generate` (the web UI's Cut runs the same command) →
`build_smart_pipeline(editorial_context)` in `analysis/editorial_runtime.py` →
`SmartPipeline.run_editorial_source()` → `RuntimeEditorialPlanner.plan_source()`, which runs
preparation, the two readings, the structure and story planners, and certifies the timing.
`generate_memory()` in `generate.py` then does extract → assemble → music → upload. Hand it no
clips and it raises rather than going to find some.

| Orchestrator | Services | What it does |
|---|---|---|
| **VideoAssembler** | FFmpegProber, ClipEncoder, AssemblyEngine, AudioMixerService, TitleInserter | Assembles clips into final video |
| **SmartPipeline** | RuntimeEditorialPlanner (from `build_smart_pipeline`) | Runs the story-first selection and projects its plan into a `PipelineResult` |
| **ImmichClient** | SearchService, AllAssetsService, AssetService, PersonService, AlbumService | Talks to the Immich API |
| **TitleScreenGenerator** | RenderingService, EndingService, TripService | Creates title/ending screens |

The editorial route has Protocol-typed ports rather than services: the providers and the people
loader, the structure planner, the judges it calls out to, and `EditorialAttempt` in `operations/`
for the durable attempt tree and its OS lease. On disk each attempt is
`<cache>/editorial-runs/<key>/attempts/<id>/`, and the banked facts and
answers live in the store (the `db/` package, tables in `db/tables/annotations.py` and
`db/tables/model_answers.py`).
[ARCHITECTURE.md](https://github.com/sam-dumont/immich-memories/blob/main/ARCHITECTURE.md)
names every port and the file it lives in, with the full module map.

## Verification

[CI and quality gates](./ci.md) explain which checks run for each kind of diff. [Testing](./testing.md) covers local suites.

## How to add a feature

### A new processing capability

1. Create a service class in the relevant package (for example `processing/my_service.py`)
2. Inject it into the orchestrator's `__init__` in `video_assembler.py`
3. Add tests in `tests/test_my_service.py`

### A new API endpoint

1. Add the method to the relevant service in `api/` (for example `search_service.py`)
2. Add a delegating method on `ImmichClient` in `api/immich.py`
3. Add the model to `api/models.py` if needed, and test against a mock HTTP client

### A new memory type

1. Add the value to the `MemoryType` enum in `memory_types/registry.py`
2. Write a factory function in `memory_types/factory.py` and decorate it with `@register_preset`: the decorator *is* the registration, there is no second list to edit there
3. Add date builder logic if the type needs its own, in `memory_types/date_builders.py`
4. Add it to `OFFERED_MEMORY_TYPES` in `memory_types/registry.py` for `--memory-type`. Add its fields to `FIELDS` in `web/src/routes/create/+page.svelte` too: the Memory page has its own map and does not discover presets from the Python tuple
5. Document it in [`docs-site/docs/make/memory-types.mdx`](../make/memory-types.mdx)

### A new CLI command

1. Create a new file in `cli/` (for example `cli/my_cmd.py`) with a `register_my_commands(main)` function, like `cli/hardware_cmd.py`
2. Import it and call it with the others at the bottom of `cli/__init__.py`
3. Run `make docs-cli` to regenerate the [CLI reference](../reference/cli-reference.md): `make docs-cli-check` fails CI until you do
4. Add the docs page under `docs-site/docs/make/cli/`, add its ID to `docs-site/sidebars.ts`, and run `make docs-build`

## File naming conventions

- `_prefixed.py`: private helpers for their own package. Keep imports inside the owning package; public package entry points expose shared behavior
- `*_service.py`: composed service classes
- `*_models.py`: data models (Pydantic or dataclass)
- `*_helpers.py`: standalone helper functions
- `*.py` (no prefix): public modules and standalone classes. Re-export shims belong in
  `__init__.py` and nowhere else

<span id="ci-pipeline"></span>
<span id="quality-gates"></span>
