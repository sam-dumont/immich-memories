---
title: Choose an upgrade
---

# Choose an upgrade

Basic makes a full film on a plain NAS. Each add-on below changes one thing, and each has a cost.
[Choose your setup](../get-started/choose-your-setup.md) explains how they combine into the GPU
and Full tiers.

| Add-on | What it adds | What it costs |
| --- | --- | --- |
| [Inference on another machine](./inference.md) | Picture checks off a slow NAS | A GPU box on your network. A first month took 17 to 25 min on a J4125 NAS, 9 to 13 min on a node with a T1000 |
| [Captions](./captions.md) | Picture descriptions for selection and the sharing checks | A small local model (SmolVLM2 500M); about 507 MiB resident on a Mac with llama.cpp |
| [A text reader](./reader.md) | Refinement of the rules draft (Full), the music mood, optional titles and summary | A local model and its memory, or a hosted API: $0.01 to €0.07 per one-minute month film, and your cut's text leaves the network |
| [Render on a GPU box](./gpu-render.md) | The encode and most per-frame work moved to an NVIDIA card | A trusted worker that holds your Immich key |
| [Generated music](./music.md) | An original track for each film instead of a bundled one | ACE-Step XL: a Mac with 64 GB of unified memory or a 16 GB NVIDIA card, about 21 GB of memory and 20 GB of disk |

On one demo month, Basic took 54 s, GPU 76 s and Full 95 s, and all three picked the same 15
shots: [one month, three tiers](./tier-example.md). [Measure your setup](./measured.md) has the
rest of the numbers and the hardware behind them.
