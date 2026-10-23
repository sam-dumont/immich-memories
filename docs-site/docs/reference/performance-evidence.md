---
title: Benchmarking your own setup
---

# Benchmarking your own setup

A fast service doesn't make a fast film. Before comparing two runs, write down the release, the
hardware, the resolved tier and whether the facts were already banked. The project's own numbers
are on [Measure your setup](../better/measured.md); what to deploy is on
[Requirements](../run/requirements.md) and [Optional upgrades](../better/overview.md).

## Keep four measurements separate

| Measurement | What to record |
|---|---|
| Picture preparation | Number and type of previews, enabled producers, downloads, fresh or reused facts |
| Selection and text work | Selected shots, model, prompts, retries, input and output tokens |
| Rendering | Source media, output dimensions, frame rate, codec, encoder and title backend |
| Music | Bundled or generated track, generator model, stem separation and fallback |

Make the same cut twice to separate first-run preparation from reused facts:

```bash
immich-memories runs show RUN_ID
immich-memories report RUN_ID
```

Compare the same saved cut with the same output settings. A run that fell back to the CPU or to
a bundled track is not an accelerated run: record the fallback. The
[measured examples](../better/measured.md#longer-films-memory-and-duration) show whole-run
timings and memory by release and hardware.

## Memory

Measure the app and each service separately. Process RAM says nothing about GPU memory, and a
reachable CUDA service doesn't prove every producer ran on CUDA: read the providers in the
service's `/health`, and use container statistics and your GPU's own tools for memory.

The unified GPU worker runs one phase at a time and unloads models between phases, so numbers from
separate, always-loaded services don't tell you what it needs.

## Cost and quality

Price the provider's reported input, cached-input and output tokens at your account's rates,
retries and failed requests included; a run with missing usage gives only a floor. A local reader
has no bill, but it does have hardware and electricity.

Watch the finished film before choosing an upgrade. Valid JSON, a passing probe and a fast model
don't mean you'll prefer its edit.
