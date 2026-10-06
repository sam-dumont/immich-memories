---
title: Benchmarking your own setup
---

# Benchmarking your own setup

A service benchmark is not a whole-film benchmark. Record the release, hardware, resolved tier
and cache state before comparing runs. For the project's own numbers, see
[Measure your setup](../better/measured.md). Current deployment choices are in
[Requirements](../run/requirements.md) and [Optional upgrades](../better/overview.md).

## Keep four measurements separate

| Measurement | What to record |
|---|---|
| Picture preparation | Number and type of previews, enabled producers, downloads, fresh or reused facts |
| Selection and text work | Selected shots, model, prompts, retries, input and output tokens |
| Rendering | Source media, output dimensions, frame rate, codec, encoder and title backend |
| Music | Bundled or generated track, generator model, stem separation and fallback |

Make the same cut twice to distinguish first-run acquisition from reused work:

```bash
immich-memories runs show RUN_ID
immich-memories report RUN_ID
```

Compare the same saved cut with the same output settings. Record failures and fallback routes rather than counting them as successful accelerated runs. The [measured examples](../better/measured.md#longer-films-memory-and-duration) show whole-run timings and memory scopes by release and hardware.

## Memory

Measure the app and each service separately. Process RAM does not establish GPU memory use, and a reachable CUDA service does not prove that every producer ran on CUDA. Use the service's health response to inspect its loaded providers; use container statistics and your GPU's monitoring tools for memory.

The unified GPU worker admits one phase at a time and releases model resources between phases. This changes residency, so measurements from separate always-resident services do not establish its memory requirement.

## Cost and quality

Use the provider's reported input, cached-input and output tokens with the prices applicable to your account. Include retries, failed requests and incomplete usage reports. A local reader has hardware and electricity costs even without an API bill.

Watch the finished film before choosing an upgrade. Correct JSON, a passing API probe and a fast model do not establish that its edit is the one you prefer.
