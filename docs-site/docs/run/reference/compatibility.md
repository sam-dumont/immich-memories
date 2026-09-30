---
title: Compatibility and test evidence
---

# Compatibility and test evidence

These are dated results, not promises for every machine. For the short hardware checklist, see
[Requirements](../requirements.md).

## Supported and tested

**Tested** means run end to end, with the date and the commit or release it ran on: check the
date against your version. **Supported** means the code path exists and worked on an earlier
release, but has not been checked since: it probably works, and a report is welcome if it doesn't.
**Untested** means nobody has run it; it may work. **Conformance tested** means the individual
production features ran on synthetic fixtures; the pass count is separate from whole-film quality.

The last release on PyPI is 0.103.0, from 2026-09-17. Rows tested after that date ran on `main`
and the Docker image built from it, not on a `pip install`.

| Area | What | State | Evidence |
|---|---|---|---|
| Setup | Plain NAS (`nas` tier) | Tested | Every pull request cuts a month on a real Immich (v2 and v3); a cut, an edit and a render in the browser, 2026-09-27; 28 films on the maintainer's library (years, months, trips, seasons, people, special days), 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8) |
| Setup | GPU and model (`full` tier) | Tested | A July film on the maintainer's library, on `main`, Apple Silicon, 2026-09-28; 28 films on the maintainer's library (years, months, trips, seasons, people, special days), 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8) |
| Setup | GPU (`gpu` tier) | Tested | 28 films on the maintainer's library (years, months, trips, seasons, people, special days), 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8) |
| Immich | v2.7.5 and v3.2.2 | Tested | Checked on every pull request |
| Immich | 3.1.0 | Tested | The maintainer's library, 2026-09-28 |
| Immich | Other 2.x and 3.x releases | Supported | The version is detected at runtime; only the three above are exercised |
| Database | SQLite (the default) and PostgreSQL 16 | Tested | Both on every pull request that touches the store, since 2026-09-28 |
| Python | 3.11, 3.12, 3.13 | Tested | Every pull request, Linux and macOS |
| Platform | Apple Silicon, from source | Tested | The `full` tier film above, 2026-09-28 |
| Platform | Docker on x86 | Tested, deployment only | Every image change starts the compose file, upgrades, backs up and restores the store; no film renders in that check |
| Platform | Docker on arm64 | Untested | The image builds; it has not been run |
| Platform | Synology DS423+ (no AVX) | Supported | A one-month film on 2026-09-17, release 0.102.0 |
| Platform | Kubernetes manifests | Supported | Films on the maintainer's cluster, 2026-09-13 to 17 |
| Platform | Terraform module | Untested as shipped | An example module: adapt it to your cluster |
| GPU | NVIDIA inference service and NVENC encoding | Supported | 2026-09-17, release 0.102.0, on a T1000 |
| GPU | Intel VA-API and Quick Sync | Supported | 2026-09-11, on the DS423+ |
| GPU | AMD VA-API | Untested | The drivers ship in the image |
| Render worker | The service's own test suite | Tested | Every pull request that touches it; no dated deployment on a real GPU box |
| Reader | Local: oMLX with Gemma 4 E4B (6-bit) | Conformance tested, 29/34 with request-specific modes | [Measured comparison](../../reference/performance-evidence.md#llm-conformance): the JSON-default regression and trip classification are resolved; remaining failures concern two free-text judgments, vision contracts and period weighting |
| Reader | Local: llama.cpp, Ollama | Supported | Films on earlier releases |
| Reader | Local: vLLM, mlx-vlm served directly | Untested | |
| Reader | Hosted: OpenAI (gpt-5.6-luna) | Conformance tested, 32/34 | [Measured failures](../../reference/performance-evidence.md#llm-conformance): recorded trip place and motion description |
| Reader | Hosted: z.ai (glm-5.3-flash) | Conformance tested, 31/34 | [Measured failures](../../reference/performance-evidence.md#llm-conformance): free-text exclusion, request reading and requested pool |
| Reader | Hosted: Melious (deepseek-v4.1-flash) | Conformance tested, 32/34, `structured_output: false` | [Measured failures](../../reference/performance-evidence.md#llm-conformance): free-text request reading and requested pool |
| Reader | Hosted: Anthropic's own API | Untested | The same code path only ran through z.ai's Anthropic-compatible route |
| Reader | Hosted: Melious gemma-4-31b | Not supported | Its API refused every image (HTTP 400), 2026-09-15 |
| Captions | SmolVLM2 500M, on a Mac | Tested | 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8), the `gpu` and `full` films above |
| Captions | SmolVLM2 500M, on the CUDA inference service | Supported | 2026-09-17, release 0.102.0 |
| Captions | SmolVLM2 under llama.cpp | Untested | |
| Laya | The family-viewing pre-screen, on a Mac | Tested | 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8), the `gpu` and `full` films above |
| Laya | The family-viewing pre-screen, on CUDA | Supported | Films on earlier releases |
