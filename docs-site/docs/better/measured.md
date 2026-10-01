---
title: Measure your setup
---

# Measure your setup

A faster picture model does not guarantee a faster film. Downloads, picture preparation, captions, selection, encoding and music have different costs. Look at the stage that is slow on your machine before adding a service.

## Read one run

```bash
immich-memories runs show RUN_ID
immich-memories report RUN_ID
```

The run reports phase timings, memory and delivery. Review the report before sharing it; it sends nothing itself.

## Compare fairly

Make the same cut twice. The first run may acquire media and prepare facts; the second reuses compatible work. Keep those results separate.

When comparing an add-on, keep the scope, configuration and output format fixed. Record the commit, hardware and cache state. Compare the shots and the finished film as well as the elapsed time.

A local reader and local audio can share machine memory when the app owns their runtimes. An external server keeps its own memory resident until its own policy releases it. This can affect whether another model fits even while the server is idle.

## Inspect capabilities

```bash
immich-memories capabilities
```

This labels configuration and installation checks separately from generation evidence. It does not prove that every selected picture or finished film is right.

The [hardware guide](../run/hardware.md) covers encoding and title effects. The [preparation reference](../reference/preparation.md) explains the work that can be reused. For reproducible whole-film comparisons, use [release films](../contribute/setup-matrix.md).
